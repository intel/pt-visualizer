(function () {
  'use strict';

  angular
    .module('satt')
    .directive('blazeMap', blazeMap);

  blazeMap.$inject = ['$http', '$compile', '$rootScope', '$routeParams', 'blazeMapService'];

  function blazeMap($http, $compile, $rootScope, $routeParams,
                    blazeMapService) {
    return {
      templateUrl : 'views/blazemap.html',
      restrict: 'E',
      replace: false,
      priority: 0,
      scope: true,
      link: function BlazeLink(scope, element, attrs) {
        var createCanvas = function(w, h) {
          var canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          return canvas;
        };

        var mergeObjects = function(one, two) {
          for (var key in two) {
            one[key] = two[key];
          }
        };

        var parseHTMLColor = function(color) {
          if (color.charAt(0) !== '#') {
            throw new Error('Invalid HTML color');
          }
          color = color.replace('#', '0x');
          return parseInt(color);
        };

        var intToRGB = function(colorInt) {
          return {
            r: ((colorInt & 0xFF0000) >> 16),
            g: ((colorInt & 0x00FF00) >> 8),
            b: (colorInt & 0x0000FF)
          };
        };

        var formatByteSize = function(value) {
          if (value < 1024) {
            return value + "B";
          }
          if(value < 1024 * 1024) {
            return (value >> 10) + "KB";
          }
          return (value >> 20) + "MB";
        }

        var intToRGBAArray = function(colorInt, alpha) {
          var colorObj = intToRGB(colorInt);
          return new Uint8Array([colorObj.r, colorObj.g, colorObj.b, alpha]);
        };

        var createColorGradientSegment = function(startColor, endColor,
                                                  gradArray, index, length) {
          var start = intToRGB(parseHTMLColor(startColor));
          var end = intToRGB(parseHTMLColor(endColor));
          var delta = {
            r: end.r - start.r,
            g: end.g - start.g,
            b: end.b - start.b
          };
          var incr = {
            r: delta.r / (length - 1),
            g: delta.g / (length - 1),
            b: delta.b / (length - 1)
          };
          var arraySize = length << 2;
          for (var crtByte = 0; crtByte < arraySize; ++crtByte) {
            switch (crtByte & 3) {
              case 0: gradArray[index] = start.r; break;
              case 1: gradArray[index] = start.g; break;
              case 2: gradArray[index] = start.b; break;
              case 3:
                      gradArray[index] = 255;
                      start.r += incr.r;
                      start.g += incr.g;
                      start.b += incr.b;
              break;
            }
            index += 1;
          }
        };

        var createColorGradient = function(colorArray, gradientLength) {
          var arraySize = gradientLength << 2;
          var gradient = new Uint8Array(arraySize);
          var segmentSize = gradientLength / (colorArray.length - 1);
          var currentIndex = 0;
          for (var seg = 0; seg < colorArray.length - 1; ++seg) {
            if (seg === colorArray.length - 2) {
              segmentSize = gradientLength - (currentIndex >> 2);
            }
            createColorGradientSegment(colorArray[seg], colorArray[seg + 1],
                                       gradient, currentIndex, segmentSize);
            currentIndex += (segmentSize << 2);
          }
          return gradient;
        };

        var padStringStart = function(str, chr, len) {
          var remaining = len - str.length;
          if (remaining > 0) {
            var appendOne = '';
            var toAppend = chr;
            if ((remaining & 1) == 1) {
              appendOne = chr;
              remaining -= 1;
            }
            while(remaining > 1) {
              toAppend = toAppend + toAppend;
              remaining >>>= 1;
            }
            return appendOne + toAppend + str;
          }
          return str;
        }

        var Blaze = function(canvasObj, infoObj) {
          this.drawingSurface = canvasObj;
          this.infoObject = infoObj;
          this.width = this.drawingSurface.width;
          this.height = this.drawingSurface.height;

          this.config = {
            heatmapColors: ['#FFFFFF', '#8299ED', '#82EDA9',
                            '#DDED82', '#FF0000'],
            cursorColor: '#FF2020',
            gridColor: '#DCDCE0',
            highlightColor: '#E88F00'
          };

          this.data = null;

          this.cross = {
            x: 0,
            y: 0,
            active: false,
            color: this.config.cursorColor
          };

          this.cross.update = function(x, y) {
            this.x = x;
            this.y = y;
          };

          this.cross.draw = function(ctx) {
            if (this.active) {
              ctx.fillStyle = this.color;
              ctx.beginPath();
              ctx.fillRect(0, this.y, ctx.canvas.width, 1);
              ctx.fillRect(this.x, 0, 1, ctx.canvas.height);
              ctx.stroke();
            }
          };

          this.highlightRect = {
            x: 0,
            y: 0,
            width: 0,
            height: 0,
            active: false,
            color: this.config.highlightColor
          };

          this.highlightRect.update = function(x, y, w, h) {
            this.x = x;
            this.y = y;
            this.width = w;
            this.height = h;
          };

          this.highlightRect.draw = function(ctx) {
            if (this.active) {
              ctx.beginPath();
              ctx.strokeStyle = this.color;
              ctx.rect(this.x, this.y, this.width, this.height);
              ctx.stroke();
            }
          };

          this.overlays = [this.highlightRect, this.cross];

          this.backBuffer = createCanvas(this.width, this.height);
          this.colorGradient = createColorGradient(this.config.heatmapColors,
                                                   2048);
          this.gridColorRGBA = intToRGBAArray(
                                  parseHTMLColor(this.config.gridColor), 255);

          this.getRangeAtPos = function(y) {
            if (this.data === null) {
              return null;
            }
            for (var idx in this.data.ranges) {
              if (y >= this.data.ranges[idx].bounds.y &&
                  y <= this.data.ranges[idx].bounds.y +
                       this.data.ranges[idx].bounds.h) {
                return this.data.ranges[idx];
              }
            }
            return null;
          };

          this.highlightRange = null;

          this.formatRangeInfo = function(range) {
            return '0x' + padStringStart(
                            range.startAddress.toString(16), '0', 16) + ' - ' +
                   '0x' + padStringStart(
                            range.endAddress.toString(16), '0', 16) +
                   ' Length: ' + formatByteSize(range.bytesLength);
          };

          this.onRangeHighlight = function(range) {
            if (this.highlightRange == range) {
              return;
            }
            this.highlightRange = range;
            if (range == null) {
              this.highlightRect.active = false;
              this.infoObject.innerHTML = "";
            } else {
              this.highlightRect.active = true;
              this.highlightRect.update(0,
                                        range.bounds.y,
                                        this.width,
                                        range.bounds.h);
              this.infoObject.innerHTML = this.formatRangeInfo(range);
            }
          };

          this.updateRangeHighlight = function(y) {
            this.onRangeHighlight(this.getRangeAtPos(y));
          };

          this.drawOverlays = function(ctx) {
            for (var idx in this.overlays) {
              this.overlays[idx].draw(ctx);
            }
          };

          this.updateDrawingSurface = function() {
            var drawCtx = this.drawingSurface.getContext('2d');
            drawCtx.drawImage(this.backBuffer, 0, 0);
            this.drawOverlays(drawCtx);
          };

          this.drawOverlays = function(ctx) {
            for (var idx in this.overlays) {
              this.overlays[idx].draw(ctx);
            }
          };

          this.updateDrawingSurface = function() {
            var drawCtx = this.drawingSurface.getContext('2d');
            drawCtx.drawImage(this.backBuffer, 0, 0);
            this.drawOverlays(drawCtx);
          };

          this.onMouseMove = function(x, y) {
            this.cross.update(x, y);
            this.updateRangeHighlight(y);
            this.updateDrawingSurface();
          };

          this.onMouseEnter = function(x, y) {
            this.cross.active = true;
            this.cross.update(x, y);
            this.updateRangeHighlight(y);
            this.updateDrawingSurface();
          };

          this.onMouseLeave = function(x, y) {
            this.cross.active = false;
            this.onRangeHighlight(null);
            this.updateDrawingSurface();
          };

          this.putPixelFromRGBA = function(imageData, offset, rgba, repeat) {
            while(repeat-- > 0) {
              for (var channel = 0; channel < 4; channel++) {
                imageData[offset + channel] = rgba[channel];
              }
              offset += 4;
            }
          };

          this.putPixelFromValue = function(imageData, offset, val) {
            var gradientOffset = (val << 2);
            for (var channel = 0; channel < 4; channel++) {
              imageData[offset + channel] =
                this.colorGradient[gradientOffset + channel];
            }
          };

          this.updateBackbufferFromData = function() {
            var drawCtx = this.backBuffer.getContext('2d');

            drawCtx.fillStyle = this.config.heatmapColors[0];
            drawCtx.fillRect(0, 0, this.backBuffer.width,
                             this.backBuffer.height);

            if (this.data === null) {
              return;
            }

            drawCtx.beginPath();
            drawCtx.fillStyle = this.config.gridColor;

            var imgObj = drawCtx.getImageData(0, 0, this.backBuffer.width,
                                              this.backBuffer.height);
            var imageData = imgObj.data;

            var currentOffset = (this.width * (this.height - 1));
            this.data.ranges.forEach(function(range) {
              for (var idx in range.data) {
                var xDispl = idx % this.width;
                var offset = currentOffset + xDispl;
                if (idx >= this.width) {
                  offset -=  idx - xDispl;
                }
                this.putPixelFromValue(
                  imageData, (offset << 2), range.data[idx]);
              }
              currentOffset -= range.dataLength;
              this.putPixelFromRGBA(imageData, (currentOffset << 2),
                                    this.gridColorRGBA, this.width);
              currentOffset -= this.width;
            }, this);

            drawCtx.putImageData(imgObj, 0, 0);
          };

          this.processData = function() {
            if (this.data === null) {
              return;
            }

            this.data.ranges.sort(
              function(a, b) {
                return a.startAddress > b.startAddress ? 1 : -1;});
            var crtY = this.height;
            this.data.ranges.forEach(function(range) {
              var rangeH = range.dataLength / this.width;
              var rangeY = crtY - rangeH;
              range.bounds = {
                y: rangeY,
                h: rangeH
              };
              crtY -= (rangeH + 1);
            }, this);
          };

          this.onDataUpdate = function() {
            this.processData();
            this.updateBackbufferFromData();
            this.updateDrawingSurface();
          };

          this.updateData = function(data) {
            this.data = data;
            this.onDataUpdate();
          };
      };

      var blazeCanvas = d3.select(element[0]).select('.blazemap');
      var blazeInfo = d3.select(element[0]).select('.blazeinfo');
      var blazeMap = new Blaze(blazeCanvas.node(), blazeInfo.node());
      blazeMap.updateData(null);

      blazeCanvas.on('mouseenter',
                     function() {
                      var coords = d3.mouse(this);
                      blazeMap.onMouseEnter(coords[0], coords[1]);
                    });

      blazeCanvas.on('mouseleave',
                      function() {
                      var coords = d3.mouse(this);
                      blazeMap.onMouseLeave(coords[0], coords[1]);
                    });

      blazeCanvas.on('mousemove',
                    function() {
                      var coords = d3.mouse(this);
                      blazeMap.onMouseMove(coords[0], coords[1]);
                  });
      $http(
        {
          method: 'GET',
          url: '/api/1/heatmap/' + $routeParams.traceID +
               '/full/' + blazeCanvas.node().width + '/' +
               blazeCanvas.node().height
        })
        .success(function(respdata/*, status, headers, config*/) {
          blazeMap.updateData(respdata);
        })
        .error(function(data, status, headers, config) {
          console.log('Error retrieving full heatmap: ', status);
      });
    }
  };
}
})();