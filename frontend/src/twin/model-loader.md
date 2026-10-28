# Replacing the procedural bridge with a GLB/GLTF model

The procedural bridge is rendered from the backend component registry
(`components.geometry` descriptors). To use a surveyed/modelled asset instead:

1. Register the asset with `model_kind = "gltf"` and `model_ref` pointing at the file
   served by the frontend (e.g. `/models/my-bridge.glb`).
2. Register components whose `mesh_ref` equals the GLB node name (or keep your own IDs and
   set `mesh_ref` to the node name — this is the mesh ↔ component mapping).
3. Implement a `GltfBridgeModel` alongside `BridgeModel` that loads the file with
   `useGLTF(model_ref)`, traverses nodes, looks up `componentByMeshRef.get(node.name)` and
   applies the same selection/heat/wireframe materials and click handler.
4. Provide `bbox` for each component (computed once from the GLB and saved via the API) so
   markers, focus and camera-ray projection keep working.

Selection, markers, filters, heatmap and evidence panels do not depend on how the
geometry was produced — only on component IDs and model-space coordinates.
