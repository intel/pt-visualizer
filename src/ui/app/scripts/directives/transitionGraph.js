(function () {
    'use strict';

    angular
      .module('satt')
      .directive('transitionGraph', transitionGraph);

    transitionGraph.$inject = ['$http', '$compile', '$rootScope',
                               '$routeParams', '$sce'];

    function transitionGraph($http, $compile, $rootScope, $routeParams, sce) {
      return {
        templateUrl : 'views/transitionGraph.html',
        restrict: 'E',
        replace: false,
        priority: 0,
        scope: true,
        link: function TransitionGraphLink(scope, element, attrs) {
          const sortCritOut = 0;
          const sortCritIn = 1;

          const sortDirDesc = 0;
          const sortDirAsc = 1;

          var TransitionGraph = function(container) {
            this.container = container;
            this.data = null;
            this.boxH = 20;
            this.boxW = 400;
            this.boxSpacing = 36;
            this.maxSymbolNameLen = 48;
            this.arrowSpacing = 6;
            this.arrowsTextSpacing = 2;
            this.arrowContainer = null;
            this.lineStartColor = '#ff7200';
            this.lineEndColor = '#018aff';

            this.arrowImages = {
              left: {
                in: ['css/img/arrow_anim_left_in.gif',
                      'css/img/arrow_anim_left_off.png'],
                out:['css/img/arrow_anim_left_out.gif',
                      'css/img/arrow_anim_right_off.png'],
              },
              right: {
                in: ['css/img/arrow_anim_right_in.gif',
                      'css/img/arrow_anim_right_off.png'],
                out:['css/img/arrow_anim_right_out.gif',
                      'css/img/arrow_anim_left_off.png'],
              },
              width: 18,
              height: 10
            };

            this.arrowVOffset = (this.arrowImages.height >> 1) + 2;

            this.currentSelection = { idx: -1,
                                      leftSelected: false };

            this.currentSelection.invalidate = function() {
              this.update(-1, false);
            };

            this.currentSelection.update = function(idx, leftSelected) {
              this.idx = idx;
              this.leftSelected = leftSelected;
            };

            this.currentSelection.isEqual = function(idx, leftSelected) {
              return (this.idx === idx) && (this.leftSelected === leftSelected);
            };

            this.currentSelection.isValid = function() {
              return this.idx !== -1;
            };

            this.initScopeData = function() {
              var self = this;
              scope.availableDSOs = null;
              scope.arrowsEnabled = true;
              scope.overviewMode = true;
              scope.sortMode = {
                left: {
                  sortCriteria: sortCritOut,
                  sortDirection: [sortDirDesc, sortDirDesc]
                },
                right: {
                  sortCriteria: sortCritOut,
                  sortDirection: [sortDirDesc, sortDirDesc]
                }
              };

              scope.trustAsHtml = function(str) {
                return sce.trustAsHtml(str);
              };

              var getSortingModeHtml = function(isLeft, mode) {
                var sortMode = isLeft ? scope.sortMode.left :
                               scope.sortMode.right;
                var isModeOn = sortMode.sortCriteria === mode;
                var result = ['Outbound ', 'Inbound '][mode] +
                        ['&#x25bc;', '&#x25b2;'][sortMode.sortDirection[mode]];
                if (isModeOn) {
                  return '<b>' + result + '</b>';
                }
                return result;
              };

              this.enableSorting(false, false);

              scope.getOutSorting = function(isLeft) {
                return getSortingModeHtml(isLeft, sortCritOut);
              };

              scope.getInSorting = function(isLeft) {
                return getSortingModeHtml(isLeft, sortCritIn);
              };

              var onClickSortingMode = function(isLeft, mode) {
                var sortMode = isLeft ? scope.sortMode.left :
                               scope.sortMode.right;
                var isModeOn = sortMode.sortCriteria === mode;
                if (isModeOn) {
                  sortMode.sortDirection[mode] =
                                        (sortMode.sortDirection[mode] + 1) & 1;
                } else {
                  sortMode.sortCriteria = mode;
                }
                self.onChangeSortingMode();
              };

              scope.onClickOutSorting = function(isLeft) {
                onClickSortingMode(isLeft, sortCritOut);
              };

              scope.onClickInSorting = function(isLeft) {
                onClickSortingMode(isLeft, sortCritIn);
              };

              scope.onSelectDSOLeft = function(selection) {
                self.onSelectDSOs(true);
              };

              scope.onSelectDSORight = function(selection) {
                self.onSelectDSOs(false);
              };

              scope.onArrowsSet = function(selection) {
                self.updateArrowsVisibility(selection);
              };
            };

            this.enableSorting = function(leftEnabled, rightEnabled) {
              _.defer(function() {
                scope.$apply(function() {
                  scope.showLeftSort = leftEnabled;
                  scope.showRightSort = rightEnabled;
                });});
            };

            this.getInitialData = function() {
              var self = this;
              scope.dsosLoading = true;
              $http(
                {
                  method: 'GET',
                  url: '/api/1/alldsos/' + $routeParams.traceID
                })
                .success(function(respdata/*, status, headers, config*/) {
                  self.onLoadDSOsData(respdata);
                })
                .error(function(data, status, headers, config) {
                  scope.dsosLoading = false;
                  console.log('Error retrieving dso info: ', status);
              });
            };

            this.formatSymbolName = function(text) {
              if (text.length > this.maxSymbolNameLen) {
                return '...' +
                       text.substring(text.length - this.maxSymbolNameLen + 3);
              }
              return text;
            };

            this.clearChart = function() {
              this.container.selectAll('svg').remove();
              this.arrowContainer = null;
            };

            this.arrowTriPoints = '0, -2, -3, 5, 3, 5';

            this.createArrowEnd = function(x, y, parent, angle) {
              parent.append('polygon')
              .attr('points', this.arrowTriPoints)
              .style('stroke-width', 0)
              .style('stroke-opacity', 0)
              .style('fill', 'inherit')
              .attr('transform',
                    'translate(' + x + ', ' + y + ')' +
                    'rotate(' + angle + ', 0, 0)');
            };

            this.getAngle = function(x1, y1, x2, y2) {
              var dx = x2 - x1;
              var dy = y2 - y1;
              return (Math.atan2(dy, dx) * 180) / Math.PI;
            };

            this.createArrowLine = function(x1, y1, x2, y2, parent, count,
                                            overColor) {
              var fillColor = this.lineEndColor;
              var gradient = x1 < x2 ? 'url(#leftToRightGrad)' :
                                       'url(#rightToLeftGrad)';
              parent = parent.append('g')
                        .attr('stroke', gradient)
                        .style('fill', fillColor)
                        .on('mouseover', function() {
                          d3.select(this)
                          .attr('stroke', overColor)
                          .style('fill', overColor);
                        })
                        .on('mouseout', function() {
                          d3.select(this)
                          .attr('stroke', gradient)
                          .style('fill', fillColor);
                        });
              parent.append('title')
                      .text('x' + count);
              parent.append('line')
                      .attr('x1', x1)
                      .attr('x2', x2)
                      .attr('y1', y1)
                      .attr('y2', y2)
                      .style('stroke-width', 2)
                      .style('stroke-opacity', 1);
              var angle = this.getAngle(x1, y1, x2, y2) + 90;
              this.createArrowEnd(x2, y2, parent, angle);
            };

            this.onSelectSymbol = function(i, leftSelected) {
              if (this.currentSelection.isEqual(i, leftSelected) === false) {
                this.currentSelection.update(i, leftSelected);
                this.createFocusedChart(i, leftSelected);
              }
            };

            this.onDeselectSymbol = function() {
              this.currentSelection.invalidate();
              this.createInitialChart(this.data);
            };

            var elemOrder = function(a, b, isLeft) {
              var sortMode = isLeft ? scope.sortMode.left :
                             scope.sortMode.right;
              var sortField = ['out', 'in'][sortMode.sortCriteria];
              var diff = b[sortField] - a[sortField];
              if (sortMode.sortDirection[sortMode.sortCriteria] ===
                                                                sortDirAsc) {
                diff *= -1;
              }
              return diff;
            };

            this.leftSort = function(a, b) {
              return elemOrder(a, b, true);
            };

            this.rightSort = function(a, b) {
              return elemOrder(a, b, false);
            };

            this.onSwitchOverviewMode = function(isOn) {
              scope.overviewMode = isOn;
            };

            this.updateArrowsVisibility = function(isVisible) {
              if (this.arrowContainer !== null) {
                this.arrowContainer.attr('visibility',
                                         isVisible ? 'visible': 'hidden');
              }
            };

            this.defTwoColorGradient = function(parent, id,
                                                startColor, endColor) {
              var gradient = parent.append('linearGradient')
                                   .attr('id', id)
                                   .attr('x1', '0%')
                                   .attr('y2', '0%')
                                   .attr('x2', '100%')
                                   .attr('y2', '0%');
              gradient.append('stop')
                      .attr('offset', '0%')
                      .attr('stop-color', startColor);
              gradient.append('stop')
                      .attr('offset', '100%')
                      .attr('stop-color', endColor);
            };

            this.createSVGDefs = function(root) {
              var defs = root.append('defs');
              this.defTwoColorGradient(defs, 'leftToRightGrad',
                                       this.lineStartColor, this.lineEndColor);
              this.defTwoColorGradient(defs, 'rightToLeftGrad',
                                       this.lineEndColor, this.lineStartColor);
            };

            this.createFocusedChart = function(focusedIdx, leftSelected) {
              this.clearChart();
              var self = this;
              var filteredEdges = [];
              var leftSet = new Set();
              var rightSet = new Set();
              var totalJumps = [];

              this.data.edges.forEach(function(item) {
                var symIndex = leftSelected ? item.left : item.right;
                if (symIndex === focusedIdx) {
                  filteredEdges.push(item);
                  leftSet.add(item.left);
                  rightSet.add(item.right);
                  if (leftSelected) {
                    totalJumps[item.right] = item.count;
                  } else {
                    totalJumps[item.left] = item.count;
                  }
                }
              });

              var leftArray = Array.from(leftSet);
              var rightArray = Array.from(rightSet);
              var symbolsLeft = [];
              var symbolsRight = [];
              var idxMapLeft = [];
              var idxMapRight = [];
              leftArray.forEach(function(item, i) {
                symbolsLeft[i] = Object.assign({}, self.data.symbolsLeft[item]);
                if (leftSelected === false) {
                  symbolsLeft[i].out = totalJumps[item][0];
                  symbolsLeft[i].in = totalJumps[item][1];
                }
              });
              rightArray.forEach(function(item, i) {
                symbolsRight[i] = Object.assign({},
                                                self.data.symbolsRight[item]);
                if (leftSelected === true) {
                  symbolsRight[i].out = totalJumps[item][1];
                  symbolsRight[i].in = totalJumps[item][0];
                }
              });

              symbolsLeft.sort(this.leftSort);
              symbolsRight.sort(this.rightSort);

              symbolsLeft.forEach(function(item, i) {
                idxMapLeft[item.idx] = i;
              });
              symbolsRight.forEach(function(item, i) {
                idxMapRight[item.idx] = i;
              });

              var graph = this.createSymbolsBoxes(
                            symbolsLeft, symbolsRight,
                            function(item, leftSelected) {
                              if (self.currentSelection.isEqual(
                                          item.idx, leftSelected) === true) {
                                self.onDeselectSymbol();
                              } else {
                                self.onSelectSymbol(item.idx, leftSelected);
                              }
                            });
              this.createSVGDefs(graph);
              this.arrowContainer = graph.append('g');
              var width = this.container.node().clientWidth;
              var x1 = this.boxSpacing + this.boxW + this.arrowSpacing;
              var x2 = width - this.boxSpacing - this.boxW - this.arrowSpacing;
              filteredEdges.forEach(function(item) {
                var y1 = idxMapLeft[item.left] * (self.boxH +
                         self.boxSpacing) + self.boxSpacing -
                         self.arrowVOffset;
                var y2 = idxMapRight[item.right] * (self.boxH +
                         self.boxSpacing) + self.boxSpacing + self.boxH +
                         self.arrowVOffset;
                if (item.count[0] > 0) {
                  self.createArrowLine(x1, y1, x2, y2, self.arrowContainer,
                                       item.count[0], '#ff3300');
                }
                if (item.count[1] > 0) {
                  y1 += self.boxH + (self.arrowVOffset << 1);
                  y2 -= self.boxH + (self.arrowVOffset << 1);
                  self.createArrowLine(x2, y2, x1, y1, self.arrowContainer,
                                       item.count[1], '#ff3300');
                }
              });
              this.enableSorting(symbolsLeft.length > 1,
                                 symbolsRight.length > 1);
              this.onSwitchOverviewMode(false);
              this.updateArrowsVisibility(scope.arrowsEnabled);
            };

            this.createSymbolsBoxes = function(symbolsLeft, symbolsRight,
                                               onClick) {
              var maxSyms = Math.max(symbolsLeft.length, symbolsRight.length);
              if (maxSyms === 0) {
                return;
              }

              var height = maxSyms * this.boxH + (maxSyms + 1) *
                          this.boxSpacing;
              var width = this.container.node().clientWidth;
              var graph = this.container
                            .append('svg')
                            .attr('height', height)
                            .attr('width', width)
                            .attr('viewBox', '0 0 ' + width + ' ' + height)
                            .attr('preserveAspectRatio','none');

              var x = [this.boxSpacing,
                       width - this.boxSpacing - this.boxW];
              var d = symbolsLeft.concat(symbolsRight);
              var self = this;

              var cells = graph.selectAll('g')
                .data(d)
                .enter().append('g')
                .style('fill', '#b3cccc')
                .attr('transform', function(item, i) {
                  var tx = x[0];
                  if (i >= symbolsLeft.length) {
                    i -=  symbolsLeft.length;
                    tx = x[1];
                  }
                  tx += (self.boxW >> 1);
                  var ty = i * (self.boxH + self.boxSpacing) + self.boxSpacing +
                          (self.boxH >> 1);
                  return 'translate(' + tx + ', ' + ty + ')';
                })
                .attr('column', function(item, i) {
                  if (i < symbolsLeft.length) {
                    return 'left';
                  }
                  return 'right';
                })
                .on('mouseover', function() {
                  d3.select(this)
                  .style('fill', '#fffdcc');
                })
                .on('mouseout', function() {
                  d3.select(this)
                  .style('fill', '#b3cccc');
                })
                .on('click', function(item, i) {
                  onClick(item, i < symbolsLeft.length);
                });

              cells.append('title')
                .text(function(item) { return item.name; });

              cells.append('rect')
                .attr('x', -(self.boxW >> 1))
                .attr('y', -(self.boxH >> 1))
                .attr('width', self.boxW)
                .attr('height', self.boxH)
                .attr('stroke', '#7a7a52')
                .style('stroke-opacity', 1)
                .style('stroke-width', 2);

              cells.append('text')
                .attr('x', 0)
                .attr('y', 5)
                .attr('text-anchor', 'middle')
                .style('font-family', 'monospace')
                .style('font-size', '14px')
                .style('fill', 'black')
                .text(function(item) {
                  return self.formatSymbolName(item.name);});

              var addInfoText = function(basePosY, textOffset, imageOffset,
                                         color, elemName) {
                cells.append('image')
                  .attr('x', function() {
                    if(d3.select(this.parentNode).attr('column') === 'left') {
                      return (self.boxW >> 1) - self.arrowImages.width;
                    }
                    return -(self.boxW >> 1);
                  })
                  .attr('y', basePosY + imageOffset)
                  .attr('href', function(item) {
                    return self.arrowImages[
                                  d3.select(this.parentNode).attr('column')]
                                  [elemName][item[elemName] > 0 ? 0 : 1];
                  })
                  .attr('width', self.arrowImages.width)
                  .attr('height', self.arrowImages.height);
                cells.append('text')
                  .attr('x', function() {
                    if(d3.select(this.parentNode).attr('column') === 'left') {
                      return (self.boxW >> 1) - self.arrowImages.width -
                             self.arrowsTextSpacing;
                    }
                    return -(self.boxW >> 1) + self.arrowImages.width +
                           self.arrowsTextSpacing;
                  })
                  .attr('y', basePosY + textOffset)
                  .attr('text-anchor', function() {
                    if(d3.select(this.parentNode).attr('column') === 'left') {
                      return 'end';
                    }
                    return 'start';
                  })
                  .style('font-family', 'monospace')
                  .style('font-size', '12px')
                  .style('fill', color)
                  .text(function(item) {
                    return item[elemName];
                  });
                };

                addInfoText(-(self.boxH >> 1), -3, -self.arrowImages.height - 2,
                            '#666699', 'out');
                addInfoText((self.boxH >> 1), 11, 2, '#3366cc', 'in');

                return graph;
            };

            this.createInitialChart = function(data) {
              var self = this;
              this.clearChart();
              if (data === null) {
                return;
              }

              var symbolsLeft = Array.from(this.data.symbolsLeft)
                                     .sort(this.leftSort);
              var symbolsRight = Array.from(this.data.symbolsRight)
                                      .sort(this.rightSort);

              this.createSymbolsBoxes(symbolsLeft, symbolsRight,
                                      function(i, leftSelected) {
                                        self.onSelectSymbol(i.idx,
                                                            leftSelected); });
              this.enableSorting(symbolsLeft.length > 1,
                                 symbolsRight.length > 1);
              this.onSwitchOverviewMode(true);
            };

            this.onLoadTransitionGraph = function(data) {
              scope.dsosLoading = false;
              this.data = data;
              this.createInitialChart(data);
            };

            this.getTransitionGraph = function(leftDSO, rightDSO) {
              var self = this;
              scope.dsosLoading = true;
              $http(
                {
                  method: 'GET',
                  url: '/api/1/dsotransitions/' + $routeParams.traceID +
                       '/' + leftDSO.id + '/' + rightDSO.id
                })
                .success(function(respdata/*, status, headers, config*/) {
                  self.onLoadTransitionGraph(respdata);
                })
                .error(function(data, status, headers, config) {
                  scope.dsosLoading = false;
                  console.log('Error retrieving dso info: ', status);
              });
            };

            this.onSelectDSOs = function(leftUpdated) {
              if (scope.selectedDSOLeft.id !== -1 &&
                  scope.selectedDSORight.id !== -1) {
                    if (scope.selectedDSOLeft.id === scope.selectedDSORight.id) {
                      if (leftUpdated) {
                        scope.selectedDSORight = scope.availableDSOs[0];
                      } else {
                        scope.selectedDSOLeft = scope.availableDSOs[0];
                      }
                    } else {
                      this.getTransitionGraph(scope.selectedDSOLeft,
                                              scope.selectedDSORight);
                  }
                }
            };

            this.onLoadDSOsData = function(data) {
              data.unshift({
                id: -1,
                name: 'None'
              });
              scope.dsosLoading = false;
              scope.availableDSOs = data;
              scope.selectedDSOLeft = data[0];
              scope.selectedDSORight = data[0];
            };

            this.onChangeSortingMode = function() {
              if (this.currentSelection.isValid()) {
                this.createFocusedChart(this.currentSelection.idx,
                                        this.currentSelection.leftSelected);
              } else {
                this.createInitialChart(this.data);
              }
            };
          };

          var transitionGraph = new TransitionGraph(
                                      d3.select(element[0]).select('.graph'));
          transitionGraph.initScopeData();
          transitionGraph.getInitialData();
        }
      };
    }
})();