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

removed all the road continuation why did we even add them in the first place??

hover effect over the map whenever the mouse is over a node and then details regarding the node (junction, endpoints, loop anchor) 
same thing done for the roads included length also!!

https://data.opencity.in/dataset/bengaluru-road-width-map used this to calculate road widths and apply shading to the road renderings

remade the entire look into an awesome green terminal 90's kinda thing

refer to .env.example for api keys