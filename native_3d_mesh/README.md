# Native 3D Mesh Pipeline

This folder contains an experimental pipeline variant for 3.5D runs where each
3D chiplet is emitted as one native mesh with `dim_z > 1`.

The original pipeline represents a `3 x 3 x 4` chiplet as four separate
`3 x 3 x 1` meshes connected by inter-mesh vertical links. This variant emits
one `3 x 3 x 4` mesh and uses `vertical_links_placement: intra` plus
`vertical_links_selection: intra` for partial TSV columns.

Example:

```powershell
python native_3d_mesh/run_pipeline_mesh.py --algorithm GA --graph 4 --chiprows 3 --chipcols 3 --two5dwidth 4 --threedheight 4 --num2p5d 0 --num3d 1 --population 20 --iterations 10 --use-wsl
```

To generate only the YAML for an existing particle:

```powershell
python native_3d_mesh/generate_yaml_mesh.py Particles/GA_Particle4.txt native_3d_mesh/YAML/GA_Particle4.yaml
```
