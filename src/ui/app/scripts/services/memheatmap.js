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
    .factory('memHeatmapService', memHeatmapService);

  memHeatmapService.$inject = ['$rootScope'];

  function memHeatmapService($rootScope) {
    var service = {};
    
    service.plotDataFromDataArray = function(zValues) {
      return [{
        z: zValues,
        type: 'heatmap',
        colorscale: [[0, '#BFFFBF'], [255, '#FF0000']]
      }];
    };

    service.getArrayFromSparseData = function(data, width, height) {
      var zValues = Array.from({length: height},
        function() {
            return Array.from({length: width}, function() { return 0; });
        });
      for(var idx in data) {
        zValues[Math.floor(idx / width)][idx % width] = data[idx];
      }
      return service.plotDataFromDataArray(zValues);
    };
    
    service.getInitialData = function() {
      var heightDiv = 400;
      var widthDiv = 1600;
      var zValues = Array.from({length: heightDiv},
                      function() {
                                  return Array.from(
                                        {length: widthDiv},
                                        function() { 
                                          return Math.round(
                                                  255 * Math.random());
                                        });
                      });
      var layout = {
          title: 'Heatmap',
          margin: {
                      l:0,
                      r:0,
                      t:0,
                      b:0,
                      pad:0
          },
          width: widthDiv,
          height: heightDiv,
          datarevision: 0
      };
      return { heatmapData: service.plotDataFromDataArray(zValues),
               heatmapLayout: layout };
    };

    return service;
  }
})();
