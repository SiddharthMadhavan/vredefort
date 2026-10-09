#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <unordered_map>
#include <random>
#include "json.hpp" // Located in backend/src

using json = nlohmann::json;

struct Coordinate {
    double lon;
    double lat;
};

struct RoadEdge {
    std::string id;
    std::string source;
    std::string target;
    double length_m;
    std::vector<std::string> source_edge_ids;
    std::vector<std::string> source_feature_ids;
    std::vector<std::string> kml_road_ids;
    std::vector<Coordinate> coordinates;
};

bool loadRoadEdges(const std::string& filepath, std::vector<RoadEdge>& edges) {
    std::ifstream file(filepath);
    if (!file.is_open()) {
        return false;
    }

    try {
        json j;
        file >> j;

        if (!j.contains("features") || !j["features"].is_array()) {
            std::cerr << "Invalid GeoJSON: 'features' array not found." << std::endl;
            return false;
        }

        edges.reserve(j["features"].size());

        for (const auto& feature : j["features"]) {
            RoadEdge edge;
            edge.id = feature.value("id", "");

            if (feature.contains("properties") && feature["properties"].is_object()) {
                const auto& props = feature["properties"];
                edge.source = props.value("source", "");
                edge.target = props.value("target", "");
                edge.length_m = props.value("length_m", 0.0);

                if (props.contains("source_edge_ids") && props["source_edge_ids"].is_array()) {
                    for (const auto& eid : props["source_edge_ids"]) {
                        if (eid.is_string()) edge.source_edge_ids.push_back(eid.get<std::string>());
                    }
                }

                if (props.contains("source_feature_ids") && props["source_feature_ids"].is_array()) {
                    for (const auto& fid : props["source_feature_ids"]) {
                        if (fid.is_string()) edge.source_feature_ids.push_back(fid.get<std::string>());
                    }
                }

                if (props.contains("kml_road_ids") && props["kml_road_ids"].is_array()) {
                    for (const auto& rid : props["kml_road_ids"]) {
                        if (rid.is_string()) edge.kml_road_ids.push_back(rid.get<std::string>());
                    }
                }
            }

            if (feature.contains("geometry") && feature["geometry"].is_object()) {
                const auto& geom = feature["geometry"];
                if (geom.value("type", "") == "LineString" && geom.contains("coordinates") && geom["coordinates"].is_array()) {
                    edge.coordinates.reserve(geom["coordinates"].size());
                    for (const auto& pt : geom["coordinates"]) {
                        if (pt.is_array() && pt.size() >= 2) {
                            edge.coordinates.push_back({
                                pt[0].get<double>(),
                                pt[1].get<double>()
                            });
                        }
                    }
                }
            }

            edges.push_back(std::move(edge));
        }
    } catch (const json::parse_error& e) {
        std::cerr << "JSON Parse error: " << e.what() << std::endl;
        return false;
    }

    return true;
}

void get_next_state(double dt, std::vector<double>&dist) {
    for(int i = 0; i < dist.size(); i++) {
        dist[i] += dt*100;
    }
}



int main() {
    std::vector<std::string> possible_paths = {
        "data/bengaluru-kml-road-edges.geojson",
        "../../data/bengaluru-kml-road-edges.geojson",
        "../data/bengaluru-kml-road-edges.geojson"
    };

    std::vector<RoadEdge> edges;
    bool loaded = false;

    for (const auto& path : possible_paths) {
        if (loadRoadEdges(path, edges)) {
            std::cout << "Successfully loaded edges from: " << path << std::endl;
            loaded = true;
            break;
        }
    }

    if (!loaded || edges.empty()) {
        std::cerr << "Failed to locate or open edges file." << std::endl;
        return 1;
    }

    // -------------------------------------------------------------------------
    // 1. Map string node IDs to integer indices (0, 1, 2, ...)
    // -------------------------------------------------------------------------
    std::unordered_map<std::string, int> node_to_idx;
    int next_node_idx = 0;

    auto getNodeIndex = [&](const std::string& node_id) -> int {
        auto it = node_to_idx.find(node_id);
        if (it == node_to_idx.end()) {
            node_to_idx[node_id] = next_node_idx;
            return next_node_idx++;
        }
        return it->second;
    };

    // -------------------------------------------------------------------------
    // 2. Initialize the 3 vectors for 5 vehicles
    // -------------------------------------------------------------------------
    std::vector<int> starting_node;
    std::vector<int> ending_node;
    std::vector<double> dist_from_node;

    const size_t num_vehicles = 5;
    size_t count = std::min(num_vehicles, edges.size());

    // Random number generator
    std::random_device rd;
    std::mt19937 gen(rd());

    for (size_t i = 0; i < count; ++i) {
        int u = getNodeIndex(edges[i].source);
        int v = getNodeIndex(edges[i].target);

        starting_node.push_back(u);
        ending_node.push_back(v);

        // Pick a random offset along the edge (0.0 to length_m)
        std::uniform_real_distribution<double> dist(0.0, edges[i].length_m);
        dist_from_node.push_back(dist(gen));
    }

    // -------------------------------------------------------------------------
    // 3. Display the vectors
    // -------------------------------------------------------------------------
    std::cout << "\n--- Vehicle Initialization (" << count << " Vehicles) ---" << std::endl;
    for (size_t i = 0; i < count; ++i) {
        std::cout << "Vehicle " << i + 1 << ":" << std::endl;
        std::cout << "  Start Node Index : " << starting_node[i] 
                  << " (" << edges[i].source << ")" << std::endl;
        std::cout << "  End Node Index   : " << ending_node[i] 
                  << " (" << edges[i].target << ")" << std::endl;
        std::cout << "  Dist from Node   : " << dist_from_node[i] << " m / " 
                  << edges[i].length_m << " m" << std::endl;
    }

    return 0;
}