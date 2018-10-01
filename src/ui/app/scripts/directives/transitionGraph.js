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
          var TransitionGraph = function(container) {
            this.container = container;
            this.data = null;
            this.boxH = 20;
            this.boxW = 400;
            this.boxSpacing = 30;
            this.maxSymbolNameLen = 48;
            this.arrowSpacing = 3;

            this.initData = function() {
              var self = this;
              scope.availableDSOs = null;
              scope.onSelectDSOLeft = function(selection) {
                self.onSelectDSOs(true);
              };
              scope.onSelectDSORight = function(selection) {
                self.onSelectDSOs(false);
              };
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
            };

            this.arrowTriPoints = '0, -2, -3, 5, 3, 5';

            this.createArrowEnd = function(x, y, parent, color, angle) {
              parent.append('polygon')
              .attr('points', this.arrowTriPoints)
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
                                            color, overColor) {
              parent = parent.append('g')
                        .attr('stroke-width', 2)
                        .style('stroke', color)
                        .style('stroke-opacity', 1)
                        .style('fill', color)
                        .on('mouseover', function() {
                          d3.select(this)
                          .style('stroke', overColor)
                          .style('fill', overColor);
                        })
                        .on('mouseout', function() {
                          d3.select(this)
                          .style('stroke', color)
                          .style('fill', color);
                        });
              parent.append('title')
                      .text('x' + count);
              parent.append('line')
                      .attr('x1', x1)
                      .attr('x2', x2)
                      .attr('y1', y1)
                      .attr('y2', y2)
                      .style('stroke-width', 2);
              var angle = this.getAngle(x1, y1, x2, y2) + 90;
              this.createArrowEnd(x2, y2, parent, color, angle);
            };

            this.onSelectSymbol = function(i) {
              this.createFocusedChart(i);
            };

            this.createFocusedChart = function(i) {
              this.clearChart();

              var self = this;
              var fromLeft = i < this.data.symbolsLeft.length;
              if (!fromLeft) {
                i -= this.data.symbolsLeft.length;
              }

              var filteredEdges = [];
              var leftSet = new Set();
              var rightSet = new Set();
              var totalJumps = [];

              this.data.edges.forEach(function(item) {
                var value = fromLeft ? item.left : item.right;
                if(value === i) {
                  filteredEdges.push(item);
                  leftSet.add(item.left);
                  rightSet.add(item.right);
                  if (fromLeft) {
                    totalJumps[item.right] = item.count;
                  } else {
                    totalJumps[item.left] = item.count;
                  }
                }
              });

              var leftArray = Array.from(leftSet).sort();
              var rightArray = Array.from(rightSet).sort();
              var symbolsLeft = [];
              var symbolsRight = [];
              var mapLeft = [];
              var mapRight = [];
              var revMapLeft = [];
              var revMapRight = [];
              leftArray.forEach(function(item, i) {
                symbolsLeft[i] = Object.assign({}, self.data.symbolsLeft[item]);
                if (fromLeft === false) {
                  symbolsLeft[i].out = totalJumps[item][0];
                  symbolsLeft[i].in = totalJumps[item][1];
                }
                mapLeft[i] = item;
                revMapLeft[item] = i;
              });
              rightArray.forEach(function(item, i) {
                symbolsRight[i] = Object.assign({},
                                                self.data.symbolsRight[item]);
                if (fromLeft === true) {
                  symbolsRight[i].out = totalJumps[item][1];
                  symbolsRight[i].in = totalJumps[item][0];
                }
                mapRight[i] = item;
                revMapRight[item] = i;
              });

              var graph = this.createSymbolsBoxes(
                            symbolsLeft, symbolsRight,
                            function(i) {
                              var left = i < symbolsLeft.length;
                              if (!left) {
                                i -= symbolsLeft.length;
                              }
                              if (left === fromLeft) {
                                self.createInitialChart(self.data);
                              } else {
                                var index = left ? mapLeft[i] : mapRight[i];
                                if (!left) {
                                  index += self.data.symbolsLeft.length;
                                }
                                self.createFocusedChart(index);
                              }
                            });

              var width = this.container.node().clientWidth;
              var x1 = this.boxSpacing + this.boxW + this.arrowSpacing;
              var x2 = width - this.boxSpacing - this.boxW - this.arrowSpacing;
              filteredEdges.forEach(function(item) {
                var y1 = revMapLeft[item.left] * (self.boxH +
                         self.boxSpacing) + self.boxSpacing;
                var y2 = revMapRight[item.right] * (self.boxH +
                         self.boxSpacing) + self.boxSpacing + self.boxH;
                if (item.count[0] > 0) {
                  self.createArrowLine(x1, y1, x2, y2, graph, item.count[0],
                                       '#0099cc', '#ff3300');
                }
                if (item.count[1] > 0) {
                  y1 += self.boxH;
                  y2 -= self.boxH;
                  self.createArrowLine(x2, y2, x1, y1, graph, item.count[1],
                                       '#00cc99', '#ff0066');
                }
              });
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
                  onClick(i);
                });

              cells.append('title')
                .text(function(item) { return item.name; });

              cells.append('rect')
                .attr('x', -(self.boxW >> 1))
                .attr('y', -(self.boxH >> 1))
                .attr('width', self.boxW)
                .attr('height', self.boxH)
                .style('stroke', '#7a7a52')
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

              var addInfoText = function(arrowL, arrowR, y, color, elemName) {
                cells.append('text')
                  .attr('x', function() {
                    if(d3.select(this.parentNode).attr('column') === 'left') {
                      return self.boxW >> 1;
                    }
                    return -(self.boxW >> 1);
                  })
                  .attr('y', y)
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
                    if(d3.select(this.parentNode).attr('column') === 'left') {
                      return item[elemName] + arrowL;
                    }
                    return arrowR + item[elemName];
                  });
                };

                addInfoText('>', '<', -(self.boxH >> 1) - 2, '#666699', 'out');
                addInfoText('<', '>',  (self.boxH >> 1) + 10, '#3366cc', 'in');

                return graph;
            };

            this.createInitialChart = function(data) {
              var self = this;
              this.clearChart();
              if (data === null) {
                return;
              }

              this.createSymbolsBoxes(data.symbolsLeft, data.symbolsRight,
                                      function(i) { self.onSelectSymbol(i); });
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
          };

          var transitionGraph = new TransitionGraph(
                                      d3.select(element[0]).select('.graph'));
          transitionGraph.initData();
          transitionGraph.getInitialData();
        }
      };
    }
})();