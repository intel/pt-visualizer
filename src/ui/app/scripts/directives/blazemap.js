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

        var floatsAreEqual = function(a, b) {
          return Math.abs(a - b) < 0.0000000001;
        };

        var formatByteSize = function(value) {
          if (value < 1024) {
            return value + 'B';
          }
          if (value < 1024 * 1024) {
            return (value >> 10) + 'KB';
          }
          return (value >> 20) + 'MB';
        };

        var formatPercent = function(value, decimals) {
          var toAppend = '';
          if (value > 0) {
            toAppend = '+';
          }
          if (Math.abs(value) <= 2.0) {
            return toAppend + (value * 100.0).toFixed(decimals) + '%';
          } else {
            return (value - 1.0).toFixed(decimals) + 'x';
          }
        };

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
            if ((remaining & 1) === 1) {
              appendOne = chr;
              remaining -= 1;
            }
            while(remaining > 1) {
              toAppend = toAppend + toAppend;
              remaining >>= 1;
            }
            return appendOne + toAppend + str;
          }
          return str;
        };

        var clampValue = function(value, min, max) {
          return (value < min) ? min : (value > max) ? max : value;
        };

        var Blaze = function(canvasObj, infoObj) {
          this.drawingSurface = canvasObj;
          this.infoObject = infoObj;
          this.width = this.drawingSurface.width;
          this.height = this.drawingSurface.height;
          this.transform = {
              x: 0,
              y: 0,
              width: this.width,
              height: this.height
          };
          this.scale = 1.0;
          this.scaleInc = 0.25;
          this.maxScale = 10.0;
          this.minScale = 1.0;

          this.dragInfo = {
            lastX: 0,
            lastY: 0,
            active: false
          };

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

          this.infoWindow = {
            x: 0,
            y: 0,
            width: 150,
            height: 170,
            infoBarH: 20,
            rows: 5,
            cols: 5,
            active: false,
            parent: this,
            data: null,
            spacing: 10,
            cellFontSize: 10,
            borderColor: '#536666',
            selectedColor: '#FF5964'
          };

          this.infoWindow.update = function(x, y, data) {
              this.x = x + this.spacing;
              if ((this.x + this.width) >= this.parent.width) {
                this.x = x - this.width - this.spacing - 1;
              }
              this.y = y - this.height - this.spacing;
              if (this.y < 0) {
                this.y = y + this.spacing;
              }
              this.data = data;
          };

          this.infoWindow.draw = function(ctx) {
            if (!this.active || this.data === null) {
              return;
            }
            ctx.fillStyle = this.parent.config.gridColor;
            ctx.fillRect(this.x, this.y, this.width, this.height);
            var cellW = this.width / this.cols;
            var cellH = (this.height - this.infoBarH) / this.rows;
            var crtX = this.x;
            var crtY = this.y;
            var currentR = (this.rows - 1) >> 1;
            var currentC = (this.cols - 1) >> 1;
            var crtCell = 0;
            for (var row = 0; row < this.rows; ++row) {
              for (var col = 0; col < this.cols; ++col, ++crtCell) {
                if (this.data.colorValues[crtCell] !== -1) {
                  ctx.fillStyle = this.parent.getRGBStringFromGradient(
                                                this.data.colorValues[crtCell]);
                  ctx.fillRect(crtX, crtY, cellW, cellH);
                  if (this.data.deltaValues !== null &&
                      !isNaN(this.data.deltaValues[crtCell]) &&
                      this.data.colorValues[crtCell] !== 0 &&
                      (row !== currentR || col !== currentC)) {
                    ctx.fillStyle = '#000000';
                    ctx.textAlign = 'center';
                    ctx.font = this.cellFontSize + 'px monospace';
                    ctx.fillText(formatPercent(this.data.deltaValues[crtCell]),
                                 crtX + (cellW >> 1),
                                 crtY + ((cellH - this.cellFontSize) >> 1));
                  }
                }
                crtX += cellW;
              }
              crtX = this.x;
              crtY += cellH;
            }
            ctx.lineWidth = 1;
            ctx.strokeStyle = this.borderColor;
            ctx.beginPath();
            ctx.rect(this.x, this.y, this.width, this.height);
            ctx.stroke();
            ctx.beginPath();
            ctx.strokeStyle = this.selectedColor;
            ctx.rect(this.x + cellW * ((this.cols - 1) >> 1),
                     this.y + cellH * ((this.rows - 1) >> 1),
                     cellW, cellH);
            ctx.stroke();
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

          this.overlays = [this.highlightRect, this.cross, this.infoWindow];

          this.backBuffer = createCanvas(this.width, this.height);
          this.colorGradient = createColorGradient(this.config.heatmapColors,
                                                   2048);
          this.gridColorRGBA = intToRGBAArray(
                                  parseHTMLColor(this.config.gridColor), 255);

          this.getRangeAtPos = function(y) {
            if (this.data === null) {
              return null;
            }
            y = this.toLogicalCoords(0, y)[1];
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
                   ' Length: ' + formatByteSize(range.bytesLength) +
                   ' DSO: ' + range.dso;
          };

          this.onRangeHighlight = function(range) {
            if (this.highlightRange === range) {
              return;
            }
            this.highlightRange = range;
            if (range === null) {
              this.highlightRect.active = false;
              this.infoObject.innerHTML = '';
            } else {
              this.highlightRect.active = true;
              var y = this.toPhysicalCoords(0, range.bounds.y)[1];
              this.highlightRect.update(
                                      0, y, this.width,
                                      Math.floor(range.bounds.h * this.scale));
              this.infoObject.innerHTML = this.formatRangeInfo(range);
            }
          };

          this.updateRangeHighlight = function(y) {
            this.onRangeHighlight(this.getRangeAtPos(y));
          };

          this.retrievePointsAround = function(x, y, w, h, range) {
            y = Math.floor(range.bounds.h - (y - range.bounds.y) - 1);
            var startX = x - ((w - 1) >> 1);
            var endX = startX + w;
            var startY = y + ((h - 1) >> 1);
            var endY = startY - h;
            var arr = [];
            var deltaValues = [];
            var hitCount = -1;
            var foundOne = false;
            for (var crtY = startY; crtY > endY; --crtY) {
              var overIndexStart = crtY * this.width;
              for (var crtX = startX; crtX < endX; ++crtX) {
                var crtVal = -1;
                var absVal = NaN;
                if (crtX >= 0 &&
                    crtY >= 0 &&
                    crtY < range.bounds.h &&
                    crtX < this.width) {
                  var overIndex = overIndexStart + crtX;
                  if (overIndex in range.data) {
                    crtVal = range.data[overIndex][0];
                    absVal = range.data[overIndex][1];
                    foundOne = true;
                  } else {
                    crtVal = 0;
                    absVal = 0;
                  }
                }
                if (crtX === x && crtY === y) {
                  hitCount = absVal;
                }
                arr.push(crtVal);
                deltaValues.push(absVal);
              }
            }
            if (foundOne === false) {
              return null;
            }
            if (!isNaN(hitCount) && hitCount !== 0) {
              for (var idx in deltaValues) {
                if (!isNaN(deltaValues[idx])) {
                  deltaValues[idx] = (deltaValues[idx] - hitCount) / hitCount;
                }
              }
            } else {
              deltaValues = null;
            }
            var startAddress = range.startAddress +
                                (y * this.width + x) * this.data.mapping;
            var endAddress = startAddress + this.data.mapping;
            return {
              colorValues: arr,
              deltaValues: deltaValues,
              hitCount: hitCount,
              startAddress: startAddress,
              endAddress: endAddress
            };
          };

          this.updateDataPointHighlight = function(x, y, range) {
            if (range === null) {
              this.infoWindow.active = false;
            } else {
              this.infoWindow.active = true;
              var logical = this.toLogicalCoords(x, y);
              this.infoWindow.update(x, y,
                this.retrievePointsAround(logical[0], logical[1],
                                          this.infoWindow.cols,
                                          this.infoWindow.rows, range));
            }
          };

          this.drawOverlays = function(ctx) {
            for (var idx in this.overlays) {
              this.overlays[idx].draw(ctx);
            }
          };

          this.drawOverlays = function(ctx) {
            for (var idx in this.overlays) {
              this.overlays[idx].draw(ctx);
            }
          };

          this.updateDrawingSurface = function() {
            var drawCtx = this.drawingSurface.getContext('2d');
            drawCtx.imageSmoothingEnabled = false;
            drawCtx.mozImageSmoothingEnabled = false;
            drawCtx.webkitImageSmoothingEnabled = false;
            drawCtx.msImageSmoothingEnabled = false;
            if (this.scale > 1.0) {
              drawCtx.drawImage(this.backBuffer,
                                this.transform.x, this.transform.y,
                                this.transform.width,
                                this.transform.height);
            } else {
              drawCtx.drawImage(this.backBuffer, 0, 0);
            }
            this.drawOverlays(drawCtx);
          };

          this.onMouseMove = function(x, y, shiftKey) {
            if (this.dragInfo.active) {
               var deltaX = x - this.dragInfo.lastX;
               var deltaY = y - this.dragInfo.lastY;
               this.dragInfo.lastX = x;
               this.dragInfo.lastY = y;
               this.transform.x = clampValue(
                                    this.transform.x + deltaX,
                                    -(this.transform.width - this.width), 0);
               this.transform.y = clampValue(
                                    this.transform.y + deltaY,
                                    -(this.transform.height - this.height), 0);
            } else {
              if (shiftKey) {
                y = this.cross.y;
              }
              this.cross.active = true;
              this.cross.update(x, y);
              this.updateRangeHighlight(y);
              this.updateDataPointHighlight(x, y, this.highlightRange);
            }
            this.updateDrawingSurface();
          };

          this.onMouseEnter = function(x, y) {
            if (this.dragInfo.active) {
              this.dragInfo.lastX = x;
              this.dragInfo.lastY = y;
            } else {
              this.cross.active = true;
              this.cross.update(x, y);
              this.updateRangeHighlight(y);
              this.updateDataPointHighlight(x, y, this.highlightRange);
            }
            this.updateDrawingSurface();
          };

          this.onMouseLeave = function(x, y) {
            this.cross.active = false;
            this.onRangeHighlight(null);
            this.updateDataPointHighlight(x, y, null);
            this.updateDrawingSurface();
          };

          this.onMouseDown = function(x, y) {
            if (this.scale > 1.0) {
              this.dragInfo.active = true;
              this.dragInfo.lastX = x;
              this.dragInfo.lastY = y;
              this.onMouseLeave(x, y);
            }
          };

          this.onMouseUp = function(x, y) {
            this.dragInfo.active = false;
          };

          this.toLogicalCoords = function(x, y) {
            if (this.scale > 1.0) {
              return [Math.floor((x - this.transform.x) / this.scale),
                      Math.floor((y - this.transform.y) / this.scale)];
            }
            return [x, y];
          };

          this.toPhysicalCoords = function(x, y) {
            if (this.scale > 1.0) {
              return [Math.floor(this.transform.x + x * this.scale),
                      Math.floor(this.transform.y + y * this.scale)];
            }
            return [x, y];
          };

          this.onZoom = function(zoomIn, x, y) {
            var newScale;
            if (zoomIn) {
              newScale = Math.min(this.maxScale, this.scale + this.scaleInc);
            } else {
              newScale= Math.max(this.minScale, this.scale - this.scaleInc);
            }
            if (floatsAreEqual(newScale, this.scale)) {
              return;
            }
            var logical = this.toLogicalCoords(x, y);
            this.scale = newScale;
            this.transform.width = this.width * this.scale;
            this.transform.height = this.height * this.scale;
            this.transform.x = clampValue(
                                    x - logical[0] * this.scale -
                                    this.scale / 2,
                                    -(this.transform.width - this.width), 0);
            this.transform.y = clampValue(
                                    y - logical[1] * this.scale -
                                    this.scale / 2,
                                    -(this.transform.height - this.height), 0);
            this.highlightRange = null;
            this.onMouseMove(x, y);
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

          this.getRGBStringFromGradient = function(val) {
            var gradientOffset = (val << 2);
            return 'rgb(' +  this.colorGradient[gradientOffset] + ', ' +
                    this.colorGradient[gradientOffset + 1] + ', ' +
                    this.colorGradient[gradientOffset + 2] + ')';
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
                  imageData, (offset << 2), range.data[idx][0]);
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
                        blazeMap.onMouseMove(coords[0], coords[1],
                                             d3.event.shiftKey);
                    });

      blazeCanvas.on('mousedown',
                      function() {
                        var coords = d3.mouse(this);
                        if (d3.event.target.setPointerCapture) {
                          d3.event.target.setPointerCapture(1);
                        } else if (d3.event.target.setCapture) {
                          d3.event.target.setCapture();
                        }
                        blazeMap.onMouseDown(coords[0], coords[1]);
                    });

      blazeCanvas.on('mouseup',
                      function() {
                        var coords = d3.mouse(this);
                        blazeMap.onMouseUp(coords[0], coords[1]);
                    });

      blazeCanvas.on('wheel',
                      function() {
                        var coords = d3.mouse(this);
                        blazeMap.onZoom(d3.event.deltaY < 0, coords[0],
                                        coords[1]);
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
