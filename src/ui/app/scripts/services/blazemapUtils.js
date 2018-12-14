/*
// Copyright (c) 2018 Intel Corporation
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
*/

(function () {

  'use strict';

  angular
    .module('satt')
    .factory('blazeMapUtils', blazeMapUtils);

    blazeMapUtils.$inject = ['$rootScope'];

  function blazeMapUtils($rootScope) {
    return {
      createCanvas: function(w, h) {
        var canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        return canvas;
      },

      checkIfCanvasIsWritable: function(canvas) {
        var color = '#FF00FF';
        var drawCtx = canvas.getContext('2d');
        var targetX = canvas.width - 2;
        var targetY = canvas.height - 2;
        drawCtx.fillStyle = color;
        drawCtx.fillRect(targetX, targetY, 1, 1);
        var imgObj = drawCtx.getImageData(targetX, targetY, 1, 1);
        return imgObj !== null &&
               imgObj.data.length > 2 &&
               imgObj.data[0] === 255 &&
               imgObj.data[1] === 0 &&
               imgObj.data[2] === 255;
      },

      mergeObjects: function(one, two) {
        for (var key in two) {
          one[key] = two[key];
        }
      },

      parseHTMLColor: function(color) {
        if (color.charAt(0) !== '#') {
          throw new Error('Invalid HTML color');
        }
        color = color.replace('#', '0x');
        return parseInt(color);
      },

      intToRGB: function(colorInt) {
        return {
          r: ((colorInt & 0xFF0000) >> 16),
          g: ((colorInt & 0x00FF00) >> 8),
          b: (colorInt & 0x0000FF)
        };
      },

      floatsAreEqual: function(a, b) {
        return Math.abs(a - b) < 0.0000000001;
      },

      distanceBetweenSq: function(x1, y1, x2, y2) {
        var xDiff = x2 - x1;
        var yDiff = y2 - y1;
        return (xDiff * xDiff) + (yDiff * yDiff);
      },

      alignValueTo: function(val, to) {
        if (val === 0) { return to; }
        var md = val % to;
        return md === 0 ? val : val + (to - md);
      },

      closestAlignedValueTo: function(val, to) {
        return val - (val % to);
      },

      formatByteSize: function(value, precision) {
        precision = (typeof precision !== 'undefined') ? precision : 0;
        if (value < 1024) {
          return value + 'B';
        }
        if (value < 1024 * 1024) {
          if (precision === 0) {
            return (value >> 10) + 'KB';
          }
          return parseFloat((value / 1024.0).toFixed(precision)) + 'KB';
        }
        if (precision === 0) {
          return (value >> 20) + 'MB';
        }
        return parseFloat((value / (1024.0 * 1024.0)).toFixed(precision)) +
               'MB';
      },

      formatPercent: function(value, decimals) {
        var toAppend = '';
        if (value > 0) {
          toAppend = '+';
        }
        if (Math.abs(value) <= 2.0) {
          return toAppend + (value * 100.0).toFixed(decimals) + '%';
        } else {
          return (value - 1.0).toFixed(decimals) + 'x';
        }
      },

      intToRGBAArray: function(colorInt, alpha) {
        var colorObj = this.intToRGB(colorInt);
        return new Uint8Array([colorObj.r, colorObj.g, colorObj.b, alpha]);
      },

      putPixelFromRGBA: function(imageData, offset, rgba, repeat) {
        while(repeat-- > 0) {
          for (var channel = 0; channel < 4; ++channel) {
            imageData[offset + channel] = rgba[channel];
          }
          offset += 4;
        }
      },

      createColorGradientSegment: function(startColor, endColor,
                                           gradArray, index, length) {
        var start = this.intToRGB(this.parseHTMLColor(startColor));
        var end = this.intToRGB(this.parseHTMLColor(endColor));
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
      },

      createColorGradient: function(colorArray, gradientLength) {
        var arraySize = gradientLength << 2;
        var gradient = new Uint8Array(arraySize);
        var segmentSize = gradientLength / (colorArray.length - 1);
        var currentIndex = 0;
        for (var seg = 0; seg < colorArray.length - 1; ++seg) {
          if (seg === colorArray.length - 2) {
            segmentSize = gradientLength - (currentIndex >> 2);
          }
          this.createColorGradientSegment(colorArray[seg], colorArray[seg + 1],
                                          gradient, currentIndex, segmentSize);
          currentIndex += (segmentSize << 2);
        }
        return gradient;
      },

      padStringStart: function(str, chr, len) {
        var remaining = len - str.length;
        if (remaining > 0) {
          var appendOne = '';
          var toAppend = '';
          if ((remaining & 1) === 1) {
            appendOne = chr;
            remaining -= 1;
          }
          if (remaining > 1) {
            toAppend = chr;
            while(remaining > 1) {
              toAppend = toAppend + toAppend;
              remaining >>= 1;
            }
          }
          return appendOne + toAppend + str;
        }
        return str;
      },

      addressToString: function(address, length) {
        length = (typeof length !== 'undefined') ? length : 16;
        return '0x' + this.padStringStart(address.toString(16), '0', length);
      },

      symbolOffsetToString: function(symbol, offset) {
        if (symbol.length > 32) {
          symbol = symbol.substring(0, 29) + '...';
        }
        return symbol + '+' + this.addressToString(offset, 4);
      },

      formatAddrRange: function(stringOne, stringTwo) {
        var maxLen = Math.min(stringOne.length, stringTwo.length);
        var idx;
        for (idx = 0; idx < maxLen; ++idx) {
          if(stringOne[idx] !== stringTwo[idx]) { break; }
        }
        return stringOne.substring(0, idx) + '[' + stringOne.substring(idx) +
               ':' + stringTwo.substring(idx) + ']';
      },

      clampValue: function(value, min, max) {
        return (value < min) ? min : (value > max) ? max : value;
      }
    };
  }
})();
