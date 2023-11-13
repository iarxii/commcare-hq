hqDefine("geospatial/js/case_grouping_map",[
    "jquery",
    "knockout",
    'underscore',
    'hqwebapp/js/initial_page_data',
    'hqwebapp/js/bootstrap3/alert_user',
    'geospatial/js/models',
    'geospatial/js/utils'
], function (
    $,
    ko,
    _,
    initialPageData,
    alertUser,
    models,
    utils
) {

    const MAPBOX_LAYER_VISIBILITY = {
        None: 'none',
        Visible: 'visible',
    };
    const DEFAULT_MARKER_OPACITY = 1.0;
    const MAP_CONTAINER_ID = 'case-grouping-map';
    const clusterStatsInstance = new clusterStatsModel();
    let exportModelInstance;
    let groupLockModelInstance = new groupLockModel()
    let caseGroupsInstance = new caseGroupSelectModel()
    let mapMarkers = [];

    let mapModel;
    let polygonFilterInstance;

    function clusterStatsModel() {
        'use strict';
        let self = {};
        self.totalClusters = ko.observable(0);
        self.clusterMinCount = ko.observable(0);
        self.clusterMaxCount = ko.observable(0);
        return self;
    }

    function exportModel() {
        var self = {};

        self.casesToExport = ko.observableArray([]);

        self.downloadCSV = function () {
            if (!self.casesToExport().length) {
                return;
            }

            // Only cases with belonging to groups should be exported
            let exportableCases = self.casesToExport().filter(function(caseItem) {
                return caseItem.groupId;
            });

            if (!exportableCases.length) {
                // If no case belongs to a group, we export all cases
                exportableCases = self.casesToExport();
            }

            const casesToExport = _.map(exportableCases, function (caseItem) {
                return caseItem.toJson();
            });

            let csvStr = "";

            // Write headers first
            csvStr = Object.keys(casesToExport[0]).join(",");
            csvStr += "\n";

            _.forEach(casesToExport, function (itemRow) {
                csvStr += Object.keys(itemRow).map(key => itemRow[key]).join(",");
                csvStr += "\n";
            });

            // Download CSV file
            const hiddenElement = document.createElement('a');
            hiddenElement.href = 'data:text/csv;charset=utf-8,' + encodeURI(csvStr);
            hiddenElement.target = '_blank';
            hiddenElement.download = `Grouped Cases (${utils.getTodayDate()}).csv`;
            hiddenElement.click();
            hiddenElement.remove();
        };

        self.addGroupsToCases = function(caseGroups) {
            clearCaseGroups();
            self.casesToExport().forEach(caseItem => {
                const groupData = caseGroups[caseItem.itemId];
                if (groupData !== undefined) {
                    caseItem.groupId = groupData.groupId;
                    caseItem.groupCoordinates = groupData.groupCoordinates;
                }
            });
        }

        self.clearCaseGroups = function() {
            self.casesToExport().forEach(caseItem => {
                if (caseItem.groupId) {
                    caseItem.groupId = null;
                    caseItem.groupCoordinates = null;
                }
            });
        }
        return self;
    }

    function updateClusterStats() {
        const sourceFeatures = mapModel.mapInstance.querySourceFeatures('caseWithGPS', {
            sourceLayer: 'clusters',
            filter: ['==', 'cluster', true],
        });

        // Mapbox clustering creates the same cluster groups with slightly different coordinates.
        // Seems to be related to keeping track of clusters at different zoom levels.
        // There could therefore be more than one cluster that share the same ID so we should keep track
        // of these to skip them if we've gone over them already
        let uniqueClusterIds = {};
        let clusterStats = {
            total: 0,
            min: 0,
            max: 0,
        };
        for (const clusterFeature of sourceFeatures) {
            // Skip over duplicate clusters
            if (uniqueClusterIds[clusterFeature.id]) {
                continue;
            }

            uniqueClusterIds[clusterFeature.id] = true;
            clusterStats.total++;
            const pointCount = clusterFeature.properties.point_count;
            if (pointCount < clusterStats.min || clusterStats.min === 0) {
                clusterStats.min = pointCount;
            }
            if (pointCount > clusterStats.max) {
                clusterStats.max = pointCount;
            }
        }
        clusterStatsInstance.totalClusters(clusterStats.total);
        clusterStatsInstance.clusterMinCount(clusterStats.min);
        clusterStatsInstance.clusterMaxCount(clusterStats.max);
    }

    function loadMapClusters(caseList) {
        let caseLocationsGeoJson = {
            "type": "FeatureCollection",
            "features": [],
        };

        _.each(caseList, function (caseWithGPS) {
            const coordinates = caseWithGPS.itemData.coordinates;
            if (coordinates && coordinates.lat && coordinates.lng) {
                caseLocationsGeoJson["features"].push(
                    {
                        "type": "feature",
                        "properties": {
                            "id": caseWithGPS.itemId,
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [coordinates.lng, coordinates.lat],
                        },
                    }
                );
            }
        });

        if (mapModel.mapInstance.getSource('caseWithGPS')) {
            mapModel.mapInstance.getSource('caseWithGPS').setData(caseLocationsGeoJson);
        } else {
            mapModel.mapInstance.on('load', () => {
                mapModel.mapInstance.getSource('caseWithGPS').setData(caseLocationsGeoJson);
            });
        }
    }

    function getClusterLeavesAsync(clusterSource, clusterId, pointCount) {
        return new Promise((resolve, reject) => {
            clusterSource.getClusterLeaves(clusterId, pointCount, 0, (error, casePoints) => {
                if (error) {
                    reject(error);
                } else {
                    resolve(casePoints);
                }
            });
        });
    }

    function setMapLayersVisibility(visibility) {
        mapModel.mapInstance.setLayoutProperty('clusters', 'visibility', visibility);
        mapModel.mapInstance.setLayoutProperty('cluster-count', 'visibility', visibility);
        mapModel.mapInstance.setLayoutProperty('unclustered-point', 'visibility', visibility);
    }

    function collapseGroupsOnMap() {
        setMapLayersVisibility(MAPBOX_LAYER_VISIBILITY.None);
        mapMarkers.forEach((marker) => marker.remove());
        mapMarkers = [];

        exportModelInstance.casesToExport().forEach(function (caseItem) {
            const coordinates = caseItem.itemData.coordinates;
            if (!coordinates) {
                return;
            }
            const caseGroupID = caseItem.groupId;
            if (caseGroupsInstance.groupIDInVisibleGroupIds(caseGroupID)) {
                let caseGroup = caseGroupsInstance.getGroupByID(caseGroupID);
                color = caseGroup.color;
                const marker = new mapboxgl.Marker({ color: color, draggable: false });  // eslint-disable-line no-undef
                marker.setLngLat([coordinates.lng, coordinates.lat]);

                // Add the marker to the map
                marker.addTo(mapModel.mapInstance);
                mapMarkers.push(marker);
            }
        });
    }

    function caseGroupSelectModel() {
        'use strict';
        var self = {};

        self.allGroups = ko.observableArray([]);
        self.allCaseGroups;
        self.visibleGroupIDs = ko.observableArray([]);
        self.casePerGroup = {};

        self.groupIDInVisibleGroupIds = function(groupID) {
            return self.visibleGroupIDs().indexOf(groupID) !== -1;
        };

        self.getGroupByID = function(groupID) {
            return self.allGroups().find((group) => group.groupID === groupID);
        };

        self.loadCaseGroups = function(caseGroups) {
            self.allCaseGroups = caseGroups;
            // Add groups to the cases being exported

            let groupIds = [];
            for (let caseID in caseGroups) {
                let caseItem = caseGroups[caseID];
                groupIds.push(caseItem.groupId);
            }

            new Set(groupIds).forEach(id => self.allGroups.push(
                {groupID: id, color: utils.getRandomRGBColor()}
            ));

            let visibleIDs = _.map(self.allGroups(), function(group) {return group.groupID});
            self.visibleGroupIDs(visibleIDs);
            self.showAllGroups()
        };

        self.clear = function() {
            self.allGroups([]);
            self.visibleGroupIDs([]);
        };

        self.restoreMarkerOpacity = function() {
            mapMarkers.forEach(function(marker) {
                setMarkerOpacity(marker, DEFAULT_MARKER_OPACITY);
            });
        };

        self.highlightGroup = function(group) {
            exportModelInstance.casesToExport().forEach(caseItem => {
                    let caseIsInGroup = caseItem.groupId === group.groupID;
                    let opacity = DEFAULT_MARKER_OPACITY
                    if (!caseIsInGroup) {
                        opacity = 0.2;
                    }
                    let marker = mapMarkers.find((marker) => {
                        let markerCoordinates = marker.getLngLat();
                        let caseCoordinates = caseItem.itemData.coordinates;
                        let latEqual = markerCoordinates.lat === caseCoordinates.lat;
                        let lonEqual = markerCoordinates.lng === caseCoordinates.lng;
                        return latEqual && lonEqual;
                    });
                    if (marker) {
                        setMarkerOpacity(marker, opacity);
                        }
            });
        };

        function setMarkerOpacity(marker, opacity) {
            let element = marker.getElement();
            element.style.opacity = opacity;
        };

        self.showSelectedGroups = function() {
            if (!self.allCaseGroups) {
                return;
            }

            let filteredCaseGroups = {};
            for (const caseID in self.allCaseGroups) {
                if (self.groupIDInVisibleGroupIds(self.allCaseGroups[caseID].groupId)) {
                    filteredCaseGroups[caseID] = self.allCaseGroups[caseID];
                }
            }
            exportModelInstance.addGroupsToCases(filteredCaseGroups);
            collapseGroupsOnMap();
        };

        self.showAllGroups = function() {
            if (!self.allCaseGroups) {
                return;
            }
            exportModelInstance.addGroupsToCases(self.allCaseGroups);
            self.visibleGroupIDs(_.map(self.allGroups(), function(group) {return group.groupID}));
            collapseGroupsOnMap();

        };
        return self;
    }

    async function setCaseGroups() {
        const sourceFeatures = mapModel.mapInstance.querySourceFeatures('caseWithGPS', {
            sourceLayer: 'clusters',
            filter: ['==', 'cluster', true],
        });
        const clusterSource = mapModel.mapInstance.getSource('caseWithGPS');
        let caseGroups = {};
        let failedClustersCount = 0;
        processedCluster = {}

        for (const cluster of sourceFeatures) {
            const clusterId = cluster.properties.cluster_id;
            if (!processedCluster[clusterId]) {
                processedCluster[clusterId] = true;
            }

            const pointCount = cluster.properties.point_count;

            try {
                const casePoints = await getClusterLeavesAsync(clusterSource, clusterId, pointCount);
                const groupUUID = utils.uuidv4();
                for (const casePoint of casePoints) {
                    const caseId = casePoint.properties.id;
                    caseGroups[caseId] = {
                        groupId: groupUUID,
                        groupCoordinates: {
                            lng: cluster.geometry.coordinates[0],
                            lat: cluster.geometry.coordinates[1],
                        },
                    };
                }
            } catch (error) {
                failedClustersCount += 1;
            }
        }
        if (failedClustersCount > 0) {
            const message = _.template(gettext("Something went wrong processing <%- failedClusters %> groups. These groups will not be exported."))({
                failedClusters: failedClustersCount,
            });
            alertUser.alert_user(message, 'danger');
        }

        caseGroupsInstance.loadCaseGroups(caseGroups);
    }

    function clearCaseGroups() {
        setMapLayersVisibility(MAPBOX_LAYER_VISIBILITY.Visible);
        mapMarkers.forEach((marker) => marker.remove());
        mapMarkers = [];
        exportModelInstance.clearCaseGroups();
        caseGroupsInstance.allCaseGroups = undefined;
    }

    function groupLockModel() {
        'use strict';
        var self = {};

        self.groupsLocked = ko.observable(false);

        self.toggleGroupLock = function () {
            // reset the warning banner
            self.groupsLocked(!self.groupsLocked());
            if (self.groupsLocked()) {
                mapModel.mapInstance.scrollZoom.disable();
                setCaseGroups();
            } else {
                mapModel.mapInstance.scrollZoom.enable();
                clearCaseGroups();
                caseGroupsInstance.clear();
            }
        };
        return self;
    }

    $(function () {
        let caseModels = [];
        exportModelInstance = new exportModel();

        // Parses a case row (which is an array of column values) to an object, using caseRowOrder as the order of the columns
        function parseCaseItem(caseItem, caseRowOrder) {
            let caseObj = {};
            for (const propKey in caseRowOrder) {
                const propIndex = caseRowOrder[propKey];
                caseObj[propKey] = caseItem[propIndex];
            }
            return caseObj;
        }

        function loadCases(rawCaseData) {
            caseModels = [];
            const caseRowOrder = initialPageData.get('case_row_order');
            for (const caseItem of rawCaseData) {
                const caseObj = parseCaseItem(caseItem, caseRowOrder);
                const caseModelInstance = new models.GroupedCaseMapItem(caseObj.case_id, {coordinates: caseObj.gps_point}, caseObj.link);
                caseModels.push(caseModelInstance);
            }
            mapModel.caseMapItems(caseModels);
            exportModelInstance.casesToExport(caseModels);

            mapModel.fitMapBounds(caseModels);
        }

        function initMap() {
            mapModel = new models.Map(true);
            mapModel.initMap(MAP_CONTAINER_ID);

            mapModel.mapInstance.on('moveend', updateClusterStats);
            mapModel.mapInstance.on("draw.update", (e) => {
                polygonFilterInstance.addPolygonsToFilterList(e.features);
            });
            mapModel.mapInstance.on('draw.delete', function (e) {
                polygonFilterInstance.removePolygonsFromFilterList(e.features);
            });
            mapModel.mapInstance.on('draw.create', function (e) {
                polygonFilterInstance.addPolygonsToFilterList(e.features);
            });
        }

        $(document).ajaxComplete(function (event, xhr, settings) {
            const isAfterReportLoad = settings.url.includes('geospatial/async/case_grouping_map/');
            if (isAfterReportLoad) {
                $("#export-controls").koApplyBindings(exportModelInstance);
                $("#lock-groups-controls").koApplyBindings(groupLockModelInstance);
                initMap();
                $("#clusterStats").koApplyBindings(clusterStatsInstance);
                polygonFilterInstance = new models.PolygonFilter(mapModel, true, false);
                polygonFilterInstance.loadPolygons(initialPageData.get('saved_polygons'));
                $("#polygon-filters").koApplyBindings(polygonFilterInstance);

                $("#caseGroupSelect").koApplyBindings(caseGroupsInstance);
                return;
            }

            const isAfterDataLoad = settings.url.includes('geospatial/json/case_grouping_map/');
            if (!isAfterDataLoad) {
                return;
            }

            // Hide the datatable rows but not the pagination bar
            $('.dataTables_scroll').hide();

            const caseData = xhr.responseJSON.aaData;
            if (caseData.length) {
                loadCases(caseData);
                loadMapClusters(caseModels);
            }
        });
    });
});
