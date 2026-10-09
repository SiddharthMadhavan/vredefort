#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include "json.hpp" // json.hpp located in backend/src

using json = nlohmann::json;

// Structure for each node in the graph
struct Node {
    std::string id;
    double lon;
    double lat;
    int degree;
    int number;
    std::string kind;
    std::vector<std::string> edge_ids;
};

// Structure for graph metadata and the node array
struct RoadGraph {
    int schema_version;
    bool directed;
    bool multigraph;
    std::string crs;
    std::vector<Node> nodes;
};

bool loadRoadGraph(const std::string& filepath, RoadGraph& graph) {
    std::ifstream file(filepath);
    if (!file.is_open()) {
        std::cerr << "Error: Could not open file at: " << filepath << std::endl;
        return false;
    }

    try {
        json j;
        file >> j;

        // Parse root-level graph properties
        graph.schema_version = j.value("schema_version", 0);
        graph.directed = j.value("directed", false);
        graph.multigraph = j.value("multigraph", false);
        graph.crs = j.value("coordinate_reference_system", "");

        // Parse nodes array
        if (j.contains("nodes") && j["nodes"].is_array()) {
            graph.nodes.reserve(j["nodes"].size());

            for (const auto& item : j["nodes"]) {
                Node node;
                node.id = item.value("id", "");
                node.lon = item.value("lon", 0.0);
                node.lat = item.value("lat", 0.0);
                node.degree = item.value("degree", 0);
                node.number = item.value("number", 0);
                node.kind = item.value("kind", "");

                if (item.contains("edge_ids") && item["edge_ids"].is_array()) {
                    for (const auto& edge_id : item["edge_ids"]) {
                        node.edge_ids.push_back(edge_id.get<std::string>());
                    }
                }

                graph.nodes.push_back(node);
            }
        }
    } catch (const json::parse_error& e) {
        std::cerr << "JSON Parse error: " << e.what() << std::endl;
        return false;
    }

    return true;
}

int main() {
    // Relative paths depend on where the program is executed from.
    // We check root (vredefort/) first, then fallback to relative from backend/src/.
    std::vector<std::string> possible_paths = {
        "data/bengaluru-kml-road-graph.json",        // Executing from workspace root (vredefort)
        "../../data/bengaluru-kml-road-graph.json",  // Executing from backend/src
        "../data/bengaluru-kml-road-graph.json"      // Executing from backend/
    };

    RoadGraph graph;
    bool loaded = false;

    for (const auto& path : possible_paths) {
        if (loadRoadGraph(path, graph)) {
            std::cout << "Successfully loaded graph from: " << path << std::endl;
            loaded = true;
            break;
        }
    }

    if (!loaded) {
        std::cerr << "Failed to find or open bengaluru-kml-road-graph.json." << std::endl;
        return 1;
    }

    // Inspect the loaded data
    std::cout << "------------------------------------" << std::endl;
    std::cout << "CRS: " << graph.crs << std::endl;
    std::cout << "Total Nodes: " << graph.nodes.size() << std::endl;

    if (!graph.nodes.empty()) {
        const auto& first = graph.nodes[0];
        std::cout << "\nSample Node (Index 0):" << std::endl;
        std::cout << "  ID:       " << first.id << std::endl;
        std::cout << "  Coord:    (" << first.lon << ", " << first.lat << ")" << std::endl;
        std::cout << "  Kind:     " << first.kind << std::endl;
        std::cout << "  Degree:   " << first.degree << std::endl;
        std::cout << "  Edges (" << first.edge_ids.size() << "): ";
        for (const auto& eid : first.edge_ids) {
            std::cout << eid << " ";
        }
        std::cout << std::endl;
    }

    

    return 0;
}