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

            this.arrowTriPoints = '0, -5, -3, 5, 3, 5';

            this.createArrowEnd = function(x, y, parent, color, angle) {
              parent.append('polygon')
              .attr('points', this.arrowTriPoints)
              .attr('transform',
                    'translate(' + x + ', ' + y + ')' +
                    'rotate(' + angle + ', 0, 0)')
              .style('fill', color);
            };

            this.getAngle = function(x1, y1, x2, y2) {
              var dx = x2 - x1;
              var dy = y2 - y1;
              return (Math.atan2(dy, dx) * 180) / Math.PI;
            };

            this.createArrowLine = function(x1, y1, x2, y2, parent, count,
                                            color) {
              parent.append('line')
              .attr('x1', x1)
              .attr('x2', x2)
              .attr('y1', y1)
              .attr('y2', y2)
              .style('stroke', color)
              .style('stroke-opacity', 1)
              .style('stroke-width', 1);
              var angle = this.getAngle(x1, y1, x2, y2) + 90;
              this.createArrowEnd(x2, y2, parent, color, angle);
            };

            this.createChart = function(data) {
              this.clearChart();

              if (data == null) {
                return;
              }

              var maxSyms = Math.max(data.symbolsLeft.length,
                                     data.symbolsRight.length);
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
              var d = data.symbolsLeft.concat(data.symbolsRight);
              var self = this;

              graph.selectAll('rect')
                .data(d)
                .enter().append('rect')
                .attr('x', function(item, i) {
                  return i < data.symbolsLeft.length ? x[0] : x[1];
                })
                .attr('y', function(item, i) {
                  if (i >= data.symbolsLeft.length) {
                    i -=  data.symbolsLeft.length;
                  }
                  return i * (self.boxH + self.boxSpacing) + self.boxSpacing;
                })
                .attr('width', self.boxW)
                .attr('height', self.boxH)
                .style('fill', '#b3cccc')
                .style('stroke', '#7a7a52')
                .style('stroke-opacity', 1)
                .style('stroke-width', 2);

              graph.selectAll('text')
                .data(d)
                .enter().append('text')
                .attr('x', function(item, i) {
                  return (self.boxW >> 1) +
                         (i < data.symbolsLeft.length ? x[0] : x[1]);
                })
                .attr('y', function(item, i) {
                  if (i >= data.symbolsLeft.length) {
                    i -=  data.symbolsLeft.length;
                  }
                  return i * (self.boxH + self.boxSpacing) + self.boxSpacing +
                         (self.boxH >> 1) + 5;
                 })
                .attr('text-anchor', 'middle')
                .attr('font-family', 'monospace')
                .attr('text-size', '14px')
                .text(function(item) { return self.formatSymbolName(item);})
                .style('text-color', 'black');

              var x1 = x[0] + this.boxW + this.arrowSpacing;
              var x2 = x[1] - this.arrowSpacing;
              data.edges.forEach(function(item) {
                var y1 = item.left * (self.boxH + self.boxSpacing) +
                         self.boxSpacing;
                var y2 = item.right * (self.boxH + self.boxSpacing) +
                         self.boxSpacing;
                if (item.count[0] > 0) {
                  self.createArrowLine(x1, y1, x2, y2, graph, item.count,
                                       '#0099cc');
                }
                if (item.count[1] > 0) {
                  y1 += self.boxH;
                  y2 += self.boxH;
                  self.createArrowLine(x2, y2, x1, y1, graph, item.count,
                                       '#00cc99');
                }
              });
            };

            this.onLoadTransitionGraph = function(data) {
              scope.dsosLoading = false;
              this.data = data;
              this.createChart(data);
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