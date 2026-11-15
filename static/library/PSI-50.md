# PSI-50 — Development and Verification of a 3D Nucleate Pool Boiling Simulation Model Using PSI Data

- **Research area:** Fluid Physics
- **Sub-area:** Modeling
- **Flight platform:** Not Applicable
- **Project type:** Ground Investigation
- **Related investigations:** PSI-85
- **Keywords:** PSI Grant · numerical method · heat transfer rate · moment-of-fluid (MOF) procedure · multi-material systems · complex boundaries · discontinuous diffusion coefficients

## Objective

The primary objective of this investigation was to develop and validate a numerical model for further investigation of nucleate pool boiling problems under microgravity conditions.

## Hypothesis

It is hypothesized that the developed model will have the following advantages which can lead to a more accurate prediction: (1) the method can better resolve thermal boundary layers (away from triple points) using adaptive mesh refinement, (2) a novel Moment of Fluid multiphase flow algorithm will  straightforwardly prescribe a microlayer model in 3D general geometries, (3) the moment of fluid interface capturing algorithm will enable better handling of 3D problems such as bubble merging, (4) the modeling method can better conserve the boiling mass flow rate by directly exploiting the moment-of-fluid (sharp) interface reconstruction for approximating the interface heat flux in the vicinity of multiple (greater than 2) materials.

## Approach

The moment-of-fluid (MOF) procedure is employed to reconstruct the interfaces of any number of material interfaces in a computational cell. The salient features of the overall approach includes:
(i) Multi-material interfaces are represented by the piecewise linear moment-of-fluid (MOF) reconstruction, (ii)  the time derivative part of the heat equation is discretized using the backward Euler method which is a discrete maximum principle preserving time discretization scheme, (iii) the spatial derivatives part of the heat equation is discretized using the finite volume method, (iv) the temperature field is discretized on a multi-material “supermesh” in which there is just one temperature variable per material per cell, (v) the discrete location for a given variable is at the materials' centroid, (vi) “connected centroid” method is used in order to approximate fluxes, (vii) at Dirichlet or Neumann embedded interfaces,  a linear exact correction term is prescribed so that the method approximates the temperature gradient with second order accuracy.

## Research impacts

The verified model can be used to further study scenarios not investigated on ISS such as vapor bubble departure and collapse. It can also be used to identify optimal heated surface configuration for better heat transfer characteristics. In addition, the model can be used to study other problems under microgravity such as packed bed reactors. The development of nucleate pool boiling simulation tool in microgravity based on the Navier-Stokes equations from this proposed work can be used to study other boiling problems in Earth gravity such as engine cooling and cooling in electronic devices.

## Publications (1)

- A moment-of-fluid method for diffusion equations on irregular domains in multi-material systems

_Rendering of this investigation's entry in `base_de_datos/_todas_las_investigaciones_PSI.json`._