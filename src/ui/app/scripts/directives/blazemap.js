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

        var createColorGradient = function(startColor, endColor, steps) {
          var start = intToRGB(parseHTMLColor(startColor));
          var end = intToRGB(parseHTMLColor(endColor));
          var delta = {
            r: end.r - start.r,
            g: end.g - start.g,
            b: end.b - start.b
          };
          var incr = {
            r: delta.r / (steps - 1),
            g: delta.g / (steps - 1),
            b: delta.b / (steps - 1)
          };
          var arraySize = steps << 2;
          var gradient = new Uint8Array(arraySize);
          for (var crtByte = 0; crtByte < arraySize; ++crtByte) {
            switch (crtByte & 3) {
              case 0: gradient[crtByte] = start.r; break;
              case 1: gradient[crtByte] = start.g; break;
              case 2: gradient[crtByte] = start.b; break;
              case 3:
                      gradient[crtByte] = 255;
                      start.r += incr.r;
                      start.g += incr.g;
                      start.b += incr.b;
              break;
            }
          }
          return gradient;
        };

        var Blaze = function(canvasObj) {
          this.drawingSurface = canvasObj;
          console.log(this.drawingSurface);
          console.log(this.drawingSurface.width);
          this.config = {
            startColor: '#0A0A0A',
            endColor: '#FF2030',
            cursorColor: '#FF2020'
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
              var oldStrokeStyle = ctx.strokeStyle;
              ctx.strokeStyle = this.color;
              ctx.beginPath();
              ctx.moveTo(0, this.y);
              ctx.lineTo(ctx.canvas.width - 1, this.y);
              ctx.moveTo(this.x, 0);
              ctx.lineTo(this.x, ctx.canvas.height - 1);
              ctx.stroke();
              ctx.strokeStyle = oldStrokeStyle;
            }
          };

          this.overlays = [this.cross];

          this.backBuffer = createCanvas(this.drawingSurface.width,
                                         this.drawingSurface.height);
          this.colorGradient = createColorGradient(this.config.startColor,
                                                   this.config.endColor, 256);

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
            this.updateDrawingSurface();
          };

          this.onMouseEnter = function(x, y) {
            this.cross.active = true;
            this.cross.update(x, y);
            this.updateDrawingSurface();
          };

          this.onMouseLeave = function(x, y) {
            this.cross.active = false;
            this.updateDrawingSurface();
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

            drawCtx.fillStyle = this.config.startColor;
            drawCtx.fillRect(0, 0, this.backBuffer.width,
                             this.backBuffer.height);

            if (this.data === null) {
              return;
            }

            var imgObj = drawCtx.getImageData(0, 0, this.backBuffer.width,
                                              this.backBuffer.height);
            var imageData = imgObj.data;
            var mapData = this.data.data;
            for (var idx in mapData) {
              var flippedOffset = (
                this.backBuffer.height -
                Math.floor(idx / this.backBuffer.width)) *
                this.backBuffer.width +
                (idx % this.backBuffer.width);
              flippedOffset <<= 2;
              this.putPixelFromValue(
                  imageData, flippedOffset, mapData[idx]);
            }
            drawCtx.putImageData(imgObj, 0, 0);
          };

          this.onDataUpdate = function() {
            this.updateBackbufferFromData();
            this.updateDrawingSurface();
          };

          this.updateData = function(data) {
            this.data = data;
            this.onDataUpdate();
          };
      };

      var blazeCanvas = d3.select(element[0]).select('.blazemap');

      var blazeMap = new Blaze(blazeCanvas.node());
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