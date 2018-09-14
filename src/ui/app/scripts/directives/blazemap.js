(function () {
  'use strict';

  angular
    .module('satt')
    .directive('blazeMap', blazeMap);

  blazeMap.$inject = ['$http', '$compile', '$rootScope', '$routeParams',
                      'blazeMapService', '$sce'];

  function blazeMap($http, $compile, $rootScope, $routeParams,
                    blazeMapService, sce) {
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


        var alignValueTo = function(val, to) {
          if (val === 0) { return to; }
          var md = val % to;
          return md === 0 ? val : val + (to - md);
        };

        var closestAlignedValueTo = function(val, to) {
          return val - (val % to);
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

        var addressToString = function(address) {
          return '0x' + padStringStart(address.toString(16), '0', 16);
        };

        var formatAddrRange = function(stringOne, stringTwo) {
          var maxLen = Math.min(stringOne.length, stringTwo.length);
          var idx;
          for (idx = 0; idx < maxLen; ++idx) {
            if(stringOne[idx] !== stringTwo[idx]) { break; }
          }
          return stringOne.substring(0, idx) + '[' + stringOne.substring(idx) +
                 ':' + stringTwo.substring(idx) + ']';
        };

        var clampValue = function(value, min, max) {
          return (value < min) ? min : (value > max) ? max : value;
        };

        var Blaze = function(canvasObj) {
          this.drawingSurface = canvasObj;
          this.width = this.drawingSurface.width;
          this.height = this.drawingSurface.height;

          this.transform = {
              x: 0,
              y: 0,
              width: this.width,
              height: this.height,
              scale: 1.0,
              scaleInc: 0.25,
              maxScale: 10.0,
              minScale: 1.0
          };

          this.transform.toLogicalCoords = function(x, y) {
            if (this.scale > 1.0) {
              return [
                Math.floor((x - this.x) / this.scale),
                Math.floor((y - this.y) / this.scale)];
            }
            return [x - this.x, y - this.y];
          };

          this.transform.toPhysicalCoords = function(x, y) {
            if (this.scale > 1.0) {
              return [
                Math.floor(this.x + x * this.scale),
                Math.floor(this.y + y * this.scale)];
            }
            return [x + this.x, y + this.y];
          };

          this.transform.zoom = function(zoomIn, target, x, y) {
            var newScale;
            if (zoomIn) {
              newScale = Math.min(this.maxScale, this.scale + this.scaleInc);
            } else {
              newScale= Math.max(this.minScale, this.scale - this.scaleInc);
            }
            if (floatsAreEqual(newScale, this.scale)) {
              return false;
            }
            var logical = this.toLogicalCoords(x, y);
            this.scale = newScale;
            this.width = target.backBuffer.width * this.scale;
            this.height = target.backBuffer.height * this.scale;
            this.x = clampValue(x - logical[0] * this.scale -
                                this.scale / 2,
                                -(this.width - target.width), 0);
            this.y = clampValue(y - logical[1] * this.scale -
                                this.scale / 2,
                                -(this.height - target.height), 0);
            return true;
          };

          this.transform.pan = function(target, deltaX, deltaY) {
            this.x = clampValue(this.x + deltaX,
                                -(this.width - target.width), 0);
            this.y = clampValue(this.y + deltaY,
                                -(this.height - target.height), 0);
          };

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
            ctx.fillStyle = this.color;
            ctx.beginPath();
            ctx.fillRect(0, this.y, ctx.canvas.width, 1);
            ctx.fillRect(this.x, 0, 1, ctx.canvas.height);
            ctx.stroke();
          };

          this.focusedSample = {
            x: -1,
            y: -1
          };

          this.focusedSample.isSame = function(logical) {
            return this.x === logical[0] && this.y === logical[1];
          };

          this.focusedSample.update = function(logical) {
            this.x = logical[0];
            this.y = logical[1];
          };

          this.infoWindow = {
            x: 0,
            y: 0,
            width: 240,
            height: 170,
            infoBarH: 20,
            rows: 5,
            cols: 7,
            active: false,
            parent: this,
            data: null,
            spacing: 10,
            cellFontSize: 10,
            barFontSize: 12,
            borderColor: '#536666',
            selectedColor: '#FF5964'
          };

          this.infoWindow.update = function(x, y) {
              this.x = x + this.spacing;
              if ((this.x + this.width) >= this.parent.width) {
                this.x = x - this.width - this.spacing - 1;
              }
              this.y = y - this.height - this.spacing;
              if (this.y < 0) {
                this.y = y + this.spacing;
              }
          };

          this.infoWindow.getCrtSampleText = function() {
            var startAddr = addressToString(this.data.startAddress);
            var endAddr = addressToString(this.data.endAddress);
            return formatAddrRange(startAddr, endAddr) + ' > ' +
                   this.data.hitCount;
          };

          this.infoWindow.draw = function(ctx) {
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
                    ctx.textBaseline = 'middle';
                    ctx.font = this.cellFontSize + 'px sans-serif';
                    ctx.fillText(formatPercent(this.data.deltaValues[crtCell]),
                                 crtX + (cellW >> 1),
                                 crtY + (cellH >> 1));
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
            if (this.data.hitCount !== -1) {
              ctx.font = this.barFontSize + 'px sans-serif';
              ctx.fillStyle = '#000000';
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillText(this.getCrtSampleText(),
                           this.x + (this.width >> 1),
                           this.y + this.height - (this.infoBarH >> 1));
            }
          };

          this.symAtAddrRequest = {
            currentStartAddr: -1,
            pendingStartAddr: -1,
            pendingEndAddr: -1,
            requestActive: false
          };

          this.symAtAddrRequest.updateSymbolsList = function(value) {
            _.defer(function() {
              scope.$apply(function() {
                scope.symbolsForCrtSample = value;
              });
            });
          };

          this.symAtAddrRequest.update = function(startAddress, endAddress) {
            if (this.currentStartAddr !== startAddress) {
              if (this.requestActive) {
                this.pendingStartAddr = startAddress;
                this.pendingEndAddr = endAddress;
                if (startAddress !== -1) {
                  this.updateSymbolsList(['...']);
                } else {
                  this.updateSymbolsList(null);
                }
              } else {
                this.currentStartAddr = startAddress;
                this.pendingStartAddr = startAddress;
                if (startAddress !== -1) {
                  this.doRequest(startAddress, endAddress);
                } else {
                  this.updateSymbolsList(null);
                }
              }
            }
          };

          this.symAtAddrRequest.doRequest = function(startAddress, endAddress) {
            this.requestActive = true;
            var self = this;
            $http(
              {
                method: 'GET',
                url: '/api/1/symbolsataddr/' + $routeParams.traceID +
                     '/' + startAddress + '/' +
                     endAddress,
                cache: true
              })
              .success(function(respdata/*, status, headers, config*/) {
                if (self.pendingStartAddr === self.currentStartAddr) {
                  self.updateSymbolsList(respdata.length > 0 ? respdata : null);
                  self.requestActive = false;
                } else {
                  var start = self.pendingStartAddr;
                  var end = self.pendingEndAddr;
                  self.currentStartAddr = start;
                  if (start !== -1) {
                    self.doRequest(start, end);
                  } else {
                    self.requestActive = false;
                  }
                }
              })
              .error(function(data, status, headers, config) {
                console.log('Error retrieving full symbols: ', status);
            });
          };

          this.minimapWindow = {
            active: false,
            parent: this,
            scaleFactor: 0.1,
            defaultScaleFactor: 0.1
          };

          this.minimapWindow.draw = function(ctx) {
            var w = Math.floor(
                          this.parent.backBuffer.width * this.scaleFactor);
            var h = Math.floor(
                          this.parent.backBuffer.height * this.scaleFactor);
            var x = this.parent.width - w - 1;
            var y = 0;
            var vis = this.parent.transform.toLogicalCoords(0, 0);
            vis[0] *= this.scaleFactor;
            vis[1] *= this.scaleFactor;
            var totalScale = this.scaleFactor / this.parent.transform.scale;
            var visW = Math.floor(this.parent.width * totalScale);
            var visH = Math.floor(this.parent.height * totalScale);
            ctx.drawImage(this.parent.backBuffer, x, y, w, h);
            ctx.beginPath();
            ctx.strokeStyle = '#303030';
            ctx.rect(x, y, w, h);
            ctx.stroke();
            ctx.beginPath();
            ctx.strokeStyle = '#FF4060';
            ctx.rect(x + vis[0], y + vis[1], visW, visH);
            ctx.stroke();
          };

          this.minimapWindow.adjustScale = function() {
            this.scaleFactor = this.defaultScaleFactor;
            var h = this.parent.backBuffer.height * this.scaleFactor;
            var maxHeight = this.parent.height * 0.65;
            if (h > maxHeight) {
              this.scaleFactor = maxHeight / this.parent.backBuffer.height;
            }
          };

          this.minimapWindow.minimapDeltasToScreen = function(deltaX, deltaY) {
            var totalScale = this.parent.transform.scale / this.scaleFactor;
            return [Math.floor(deltaX * totalScale),
                    Math.floor(deltaY * totalScale)];
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
            ctx.beginPath();
            ctx.strokeStyle = this.color;
            ctx.rect(this.x, this.y, this.width, this.height);
            ctx.stroke();
          };

          this.overlays = [this.highlightRect, this.cross, this.infoWindow,
                           this.minimapWindow];

          this.backBuffer = createCanvas(this.width, this.height);
          this.colorGradient = createColorGradient(this.config.heatmapColors,
                                                   2048);
          this.gridColorRGBA = intToRGBAArray(
                                  parseHTMLColor(this.config.gridColor), 255);

          this.getRangeAtPos = function(y) {
            if (this.data === null) {
              return null;
            }
            y = this.transform.toLogicalCoords(0, y)[1];
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
          this.selectedRange = null;

          this.formatRangeInfo = function(range) {
            return '<b>' + addressToString(range.displStartAddress) +
                   '</b> - <b>' +
                   addressToString(range.displEndAddress) +
                   '</b> Length: <b>' + formatByteSize(range.displSize) +
                   '</b> Working size: <b>' + formatByteSize(range.wss) +
                   '</b> DSO: <b>' + range.dsoName + '</b>';
          };

          this.onRangeHighlight = function(range) {
            if (this.selectedRange !== null || this.highlightRange === range) {
              return;
            }
            this.highlightRange = range;
            if (range === null) {
              this.highlightRect.active = false;
              this.setStatusInfo('');
            } else {
              this.highlightRect.active = true;
              var y = this.transform.toPhysicalCoords(0, range.bounds.y)[1];
              this.highlightRect.update(
                                      0, y, this.width,
                                      Math.floor(range.bounds.h *
                                                 this.transform.scale));
              this.setStatusInfo(this.formatRangeInfo(range));
            }
          };

          this.onRangeSelected = function(range) {
            if (this.selectedRange !== range) {
              this.selectedRange = range;
              if (range !== null) {
                this.setStatusInfo(this.formatRangeInfo(range));
              } else {
                this.setStatusInfo('');
              }
            }
          };

          this.getActiveRange = function() {
            return this.selectedRange !== null ? this.selectedRange :
                   this.highlightRange;
          };

          this.updateRangeHighlight = function(y) {
            this.onRangeHighlight(this.getRangeAtPos(y));
          };

          this.setStatusInfo = function(text) {
            _.defer(function() {
              scope.$apply(function() {
                scope.blazeInfo = sce.trustAsHtml(text);
              });
            });
          };

          this.retrievePointsAround = function(x, y, w, h, range) {
            y = range.bounds.h - (y - range.bounds.y) - 1;
            if (y < 0 || y >= range.bounds.h) {
              return null;
            }
            var width = this.getWidthInSamples();
            x = Math.floor(x / scope.sampleSize);
            y = Math.floor(y / scope.sampleSize);
            if (x >= width) {
              return null;
            }
            var startX = x - ((w - 1) >> 1);
            var endX = startX + w;
            var startY = y + ((h - 1) >> 1);
            var endY = startY - h;
            var arr = [];
            var deltaValues = [];
            var hitCount = 0;
            var foundOne = false;
            for (var crtY = startY; crtY > endY; --crtY) {
              var overIndexStart = crtY * width;
              for (var crtX = startX; crtX < endX; ++crtX) {
                var crtVal = -1;
                var absVal = -1;
                if (crtX >= 0 &&
                    crtY >= 0 &&
                    crtY < range.bounds.h &&
                    crtX < width) {
                  var overIndex = overIndexStart + crtX - range.idxCorrection;
                  if (overIndex in range.data) {
                    crtVal = range.data[overIndex][0];
                    absVal = range.data[overIndex][1];
                    foundOne = true;
                  } else {
                    crtVal = 0;
                    absVal = 0;
                  }
                  if (crtX === x && crtY === y) {
                    hitCount = absVal;
                  }
                }
                arr.push(crtVal);
                deltaValues.push(absVal);
              }
            }
            if (foundOne === false) {
              return null;
            }
            if (hitCount > 0) {
              for (var idx in deltaValues) {
                if (deltaValues[idx] !== -1) {
                  deltaValues[idx] = (deltaValues[idx] - hitCount) / hitCount;
                } else {
                  deltaValues[idx] = NaN;
                }
              }
            } else {
              deltaValues = null;
            }
            var startAddress = range.displStartAddress +
                               (y * width + x) * this.data.bytesPerSample;
            var endAddress = startAddress + this.data.bytesPerSample - 1;
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
              this.focusedSample.update([-1, -1], null);
              this.symAtAddrRequest.update(-1, -1);
            } else {
              var logical = this.transform.toLogicalCoords(x, y);
              if (!this.focusedSample.isSame(logical)) {
                var sampleData = this.retrievePointsAround(
                                    logical[0], logical[1],
                                    this.infoWindow.cols,
                                    this.infoWindow.rows,
                                    range);
                this.focusedSample.update(logical);
                this.infoWindow.active = sampleData !== null;
                this.infoWindow.data = sampleData;
                var startAddr = -1;
                var endAddr = -1;
                if (sampleData !== null && sampleData.hitCount > 0) {
                  startAddr = sampleData.startAddress;
                  endAddr = sampleData.endAddress;
                }
                this.symAtAddrRequest.update(startAddr, endAddr);
              }
              if (this.infoWindow.active) {
                this.infoWindow.update(x, y);
              }
            }
          };

          this.drawOverlays = function(ctx) {
            this.overlays.forEach(function(overlay) {
              if(overlay.active) { overlay.draw(ctx); }
            });
          };

          this.updateDrawingSurface = function() {
            var drawCtx = this.drawingSurface.getContext('2d');
            drawCtx.imageSmoothingEnabled = false;
            drawCtx.mozImageSmoothingEnabled = false;
            drawCtx.webkitImageSmoothingEnabled = false;
            drawCtx.msImageSmoothingEnabled = false;
            drawCtx.drawImage(this.backBuffer,
                              this.transform.x, this.transform.y,
                              this.transform.width, this.transform.height);
            this.drawOverlays(drawCtx);
          };

          this.onMouseMove = function(x, y, shiftKey) {
            if (this.dragInfo.active) {
                var deltaX = x - this.dragInfo.lastX;
                var deltaY = y - this.dragInfo.lastY;
                this.dragInfo.lastX = x;
                this.dragInfo.lastY = y;
                if (shiftKey) {
                  var newDeltas = this.minimapWindow.minimapDeltasToScreen(
                                                              deltaX, deltaY);
                  deltaX = -newDeltas[0];
                  deltaY = -newDeltas[1];
                }
                this.transform.pan(this, deltaX, deltaY);
            } else {
              if (shiftKey) {
                y = this.cross.y;
              }
              this.minimapWindow.active = false;
              this.cross.active = true;
              this.cross.update(x, y);
              this.updateRangeHighlight(y);
              this.updateDataPointHighlight(x, y, this.getActiveRange());
            }
            this.updateDrawingSurface();
          };

          this.dragEnabled = function() {
            return this.transform.height !== this.height ||
                   this.transform.width !== this.width;
          };

          this.onMouseEnter = function(x, y) {
            if (this.dragInfo.active) {
              this.dragInfo.lastX = x;
              this.dragInfo.lastY = y;
            } else {
              this.cross.active = true;
              this.cross.update(x, y);
              this.updateRangeHighlight(y);
              this.updateDataPointHighlight(x, y, this.getActiveRange());
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
            if (this.dragEnabled()) {
              this.dragInfo.active = true;
              this.dragInfo.lastX = x;
              this.dragInfo.lastY = y;
              this.minimapWindow.active = true;
              this.onMouseLeave(x, y);
            }
          };

          this.onMouseUp = function(x, y) {
            this.dragInfo.active = false;
            this.minimapWindow.active = false;
          };

          this.onZoom = function(zoomIn, x, y) {
            if (this.transform.zoom(zoomIn, this, x, y)) {
              this.minimapWindow.active = true;
              this.onMouseLeave(x, y);
            }
          };

          this.putPixelFromRGBA = function(imageData, offset, rgba, repeat) {
            while(repeat-- > 0) {
              for (var channel = 0; channel < 4; ++channel) {
                imageData[offset + channel] = rgba[channel];
              }
              offset += 4;
            }
          };

          this.putPixelsFromValue = function(imageData, offset, val,
                                             size, stride) {
            var colorIndex = (val << 2);
            var rgba = [
              this.colorGradient[colorIndex],
              this.colorGradient[colorIndex + 1],
              this.colorGradient[colorIndex + 2],
              this.colorGradient[colorIndex + 3],
            ];
            for (var line = 0; line < size; ++line) {
              this.putPixelFromRGBA(imageData, offset, rgba, size);
              offset -= stride;
            }
          };

          this.getRGBStringFromGradient = function(val) {
            var gradientOffset = (val << 2);
            return 'rgb(' +  this.colorGradient[gradientOffset] + ', ' +
                    this.colorGradient[gradientOffset + 1] + ', ' +
                    this.colorGradient[gradientOffset + 2] + ')';
          };

          this.updateBackbufferFromRanges = function(ranges) {
            var newHeight = this.updateRangesBounds(ranges);
            if (newHeight !== this.backBuffer.height) {
              this.backBuffer = createCanvas(this.width, newHeight);
            }
            var drawCtx = this.backBuffer.getContext('2d');

            drawCtx.fillStyle = this.config.heatmapColors[0];
            drawCtx.fillRect(0, 0, this.backBuffer.width,
                             this.backBuffer.height);

            if (ranges === null) {
              return;
            }

            drawCtx.beginPath();
            drawCtx.fillStyle = this.config.gridColor;

            var imgObj = drawCtx.getImageData(0, 0, this.backBuffer.width,
                                              this.backBuffer.height);
            var imageData = imgObj.data;

            var width = this.getWidthInSamples();
            var imageStride = (this.backBuffer.width << 2);
            var currentOffset = imageStride * (this.backBuffer.height - 1);
            ranges.forEach(function(range) {
              for (var idx in range.data) {
                idx = parseInt(idx);
                var targetIdx = idx + range.idxCorrection;
                var xDispl = targetIdx % width;
                var yDispl = Math.floor(targetIdx / width);
                xDispl *= (scope.sampleSize << 2);
                yDispl *= (imageStride * scope.sampleSize);
                var offset = (currentOffset - yDispl) + xDispl;
                this.putPixelsFromValue(
                  imageData, offset, range.data[idx][0],
                  scope.sampleSize, imageStride);
              }
              currentOffset -= (range.bounds.h * imageStride);
              this.putPixelFromRGBA(imageData, currentOffset,
                                    this.gridColorRGBA, this.width);
              currentOffset -= imageStride;
            }, this);

            drawCtx.putImageData(imgObj, 0, 0);
          };

          this.processData = function() {
            if (this.data === null) {
              return;
            }
            this.data.ranges.sort(
              function(a, b) {
                return a.index > b.index ? 1 : -1;});
          };

          this.getWidthInSamples = function() {
            return Math.floor(this.width / scope.sampleSize);
          };

          this.updateRanges = function() {
            if (this.data === null) {
              return;
            }
            var availableDSOs = [{ id: -1,
                                   name: 'all'}];
            for (var idx = 0; idx < this.data.ranges.length; ++idx) {
              availableDSOs.push({ id: idx,
                                   name:  this.data.ranges[idx].dsoName});
            }

            scope.availableDSOs = availableDSOs;
            scope.selectedDSO = scope.availableDSOs[0];
            this.updateRangesForWidth(this.data.ranges,
                                      this.getWidthInSamples());
          };

          this.rangeFromID = function(id) {
            return id >= 0 ? this.data.ranges[id] : null;
          }

          this.updateRangesBounds = function(ranges) {
            if (ranges === null) {
              return this.height;
            }
            var totalHeight = 0;
            ranges.forEach(function(range) {
              totalHeight += range.bounds.h;
            });
            totalHeight += ranges.length - 1;
            totalHeight = Math.max(this.height, totalHeight);
            var crtY = totalHeight;
            ranges.forEach(function(range) {
              range.bounds.y = crtY - range.bounds.h;
              crtY -= (range.bounds.h + 1);
            });
            return totalHeight;
          };

          this.updateRangesForWidth = function(ranges, width) {
            ranges.forEach(function(range) {
              var startSample = Math.floor(range.startAddressAligned /
                                           scope.bytesPerSample);
              var endSample = Math.floor(range.endAddress /
                                         scope.bytesPerSample);
              var alignedStartSample = closestAlignedValueTo(
                                                  startSample, width);
              var alignedEndSample = alignValueTo(endSample + 1, width) - 1;
              range.idxCorrection = startSample - alignedStartSample;
              range.sampleCount = alignedEndSample - alignedStartSample + 1;
              range.displStartAddress = alignedStartSample *
                                        scope.bytesPerSample;
              range.displEndAddress = alignedEndSample *
                                        scope.bytesPerSample - 1;
              range.displSize = range.displEndAddress -
                                range.displStartAddress + 1;
              range.bounds = {h: scope.sampleSize *
                                 Math.floor(range.sampleCount / width),
                              y: 0};
            }, this);
          };

          this.resetTransform = function() {
            this.transform.width = this.backBuffer.width;
            this.transform.height = this.backBuffer.height;
            this.transform.x = 0;
            this.transform.y = -(this.backBuffer.height - this.height);
            this.transform.scale = 1.0;
          };

          this.onDataUpdate = function() {
            this.processData();
            this.updateRanges();
            this.updateBackbufferFromRanges(
                                  this.data !== null ? this.data.ranges : null);
            this.resetTransform();
            this.minimapWindow.adjustScale();
            this.updateDrawingSurface();
          };

          this.updateData = function(data) {
            this.data = data;
            this.onDataUpdate();
          };

          this.onUpdateDSO = function(value) {
            this.onRangeHighlight(null);
            this.onRangeSelected(this.rangeFromID(value.id));
            if (this.selectedRange === null) {
              this.updateBackbufferFromRanges(blazeMap.data.ranges);
            } else {
              this.updateBackbufferFromRanges([this.selectedRange]);
            }
            this.resetTransform();
            this.minimapWindow.adjustScale();
            this.updateDrawingSurface();
          };

          this.onUpdateSampleSize = function(value) {
            this.onRangeHighlight(null);
            this.updateRangesForWidth(this.data.ranges,
                                      this.getWidthInSamples());
            if (this.selectedRange === null) {
              this.updateBackbufferFromRanges(this.data.ranges);
            } else {
              this.updateBackbufferFromRanges([this.selectedRange]);
            }
            this.resetTransform();
            this.minimapWindow.adjustScale();
            this.updateDrawingSurface();
          };
      };

      var blazeCanvas = d3.select(element[0]).select('.blazemap');
      var blazeInfo = d3.select(element[0]).select('.blazeinfo');
      var blazeMap = new Blaze(blazeCanvas.node(), blazeInfo.node());
      blazeMap.updateData(null);

      scope.heatmapLoading = false;
      scope.bytesPerSample = 64;
      scope.sampleSize = 1;

      var enableInputEvents = function() {
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
      };

      var disableInputEvents = function() {
        blazeCanvas.on('mouseenter', null);
        blazeCanvas.on('mouseleave', null);
        blazeCanvas.on('mousedown', null);
        blazeCanvas.on('mouseup', null);
        blazeCanvas.on('wheel', null);
      };

      var doRequest = function(bytesPerSample) {
        if (scope.heatmapLoading === true) {
          return;
        }
        scope.heatmapLoading = true;
        blazeMap.setStatusInfo('<b>Loading...</b>');
        disableInputEvents();
        $http(
          {
            method: 'GET',
            url: '/api/1/heatmap/' + $routeParams.traceID +
                 '/full/' + bytesPerSample
          })
          .success(function(respdata/*, status, headers, config*/) {
            scope.heatmapLoading = false;
            blazeMap.setStatusInfo('');
            blazeMap.updateData(respdata);
            enableInputEvents();
          })
          .error(function(data, status, headers, config) {
            console.log('Error retrieving full heatmap: ', status);
        });
      };

      scope.onUpdateBpp = function(value) {
        doRequest(value);
      };

      scope.onUpdateDSO = function(value) {
        blazeMap.onUpdateDSO(value);
      };

      scope.onUpdateSampleSize = function(value) {
        blazeMap.onUpdateSampleSize(value);
      };

      doRequest(64);
    }
  };
}
})();
