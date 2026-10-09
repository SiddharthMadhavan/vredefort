# CityCollapse

benguluru emergency simulation software

TO RUN:

npm install
npm run dev

if any errors call me

added roads from benguluru using osm map's overpass api
(saved and uploaded to github so no need to import again)

calculated graph from the road data and saved it to /data no need to run the mjs again
(5000 possible junctions rest all random stuff hopefully cuda guys can do it)

hover effect over the map whenever the mouse is over a node and then details regarding the node (junction, endpoints, loop anchor) 

refer to .env.example for api keys