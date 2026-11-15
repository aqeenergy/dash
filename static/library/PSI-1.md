# PSI-1 · ELF-2 Round Robin — Round Robin - Thermophysical Property Measurement

- **Research area:** Materials Science
- **Sub-area:** Metals
- **Hardware:** JAXA ISS-ELF TEMPUS Parabolic Flight EML NASA MSFC Electrostatic Levitator (ESL)
- **Flight platform:** International Space Station (ISS)
- **Project type:** Microgravity Investigation
- **Keywords:** Electrostatic levitation · Super Alloys · Thermophysical Properties · Round Robin · pure metals · Uncertainty Analysis · ELF · A-Plus

## Objective

The key scientific objectives are:
   (a) Conducting baseline space ESL containerless property measurement experiments for two paired classes of levitation-based thermophysical properties:Density/Thermal Expansion, Viscosity/Surface Tension.
   (b) Selecting materials compatible with both electrostatic levitation (ESL) and electromagnetic levitation (EML) to allow comparison between space facilities.
   (c) Using modeling to evaluate theories used to predict the influence of gravity on propertymeasurement experiments.
   (d) Actively encouraging collaboration with existing science teams using other facilities through organizing a Round Robin test consortium

## Hypothesis

The experimental hypothesis was that in microgravity environment in the absence of stirring, high quality thermophysical property would be measured compared to the ground-based levitation facility. This was successfully observed for gold samples.

## Approach

The experimental approach involved inserting a sample carousel of 20 individual samples into the JAXA ISS-ELF facility, conditioning the test atmosphere, and conducting individual melt cycles on each sample. The heating lasers were used to precondition the sample when the sample is heated to a desired pre-bake temperature. Following the preconditioning period, the sample was charged by the electrodes and released to achieve stable positioning. The lasers were then used to thermally cycle the sample. The cycle starts by application of the highest laser heating power (activated by a control current setting in the ELF software measured in amps) until the sample is fully molten and achieved the maximum liquid superheat temperature. The heater power was then turned down to maintain the desired isothermal hold. Surface excitation was conducted using varying volage from the electrodes at this temperature. Surface tension and viscosity was measured using the droplet oscillation behavior. The laser power was then turned off to allow the molten sample to cool down. Density and cp/ε evaluations are conducted during the free cooling without any influence from the laser. Once recalescence occurred, the sample was then allowed to become fully solid at room temperature which marks the completion of a thermal cycle. Overall, processing a single melt cycle can take up to 10 - 15 minutes excluding the pre-bake. Following the cycle completion, the sample is retrieved back into the cartridge to end the test on this sample.

Using the described experimental approach several thermophysical properties were measured on a variety of metallic melts as described below:
1.	 Density –One high-speed video camera was used to monitor the sample size as a function of time during the free cooling phase. Sample edge was detected using a custom algorithm for the density measurement. The volume of the sample was calculated using a known calibration of pixels/mm3, which was subsequently correlated with temperature allowing calculation of density and thermal expansion coefficient (from the slope of the density curve). Tracking of sample mass loss was accomplished post-mission using Langmuir’s equation of evaporation.
2.	 Surface tension – After melting, the heating laser is set to a reduced value such that the sample is held at constant temperature. A sinusoidal modulation of the positioning voltage was applied to both electrodes to excite surface oscillations without changing sample position. The resulting sample deformation was measured by the high-speed linear array. A frequeny sweep was conducted to identify natural frequency. Two method was applied to identify the natural frequency from the sweep: (1) Maximum amplitude method where maximum deformation is observed at the natural frequency and (2) Excitation crossover method where the natural frequency was observed at the linear intersections  of the damped and free oscillations.  Natural frequencies identified using both methods were used to evaluate the surface tension.
3.	Viscosity – In conjunction to surface tension, viscosity was measured from the damped oscillations at the identified natural frequency. The characteristic exponential time decay from a sinusoidal fit was used to evaluate the viscosity.
4.	Specific heat capacity and emissivity – The ratio of these two quantities was evaluated from the cooling curve as monitored by the IR pyrometer after correction for conductive mass losses to the gas environment.
5.	Evaporation – Integration of the time-temperature profile allows calculation of evaporation assuming a known relationship using Langmuir’s equation for loss as a function of temperature. Pre- and post- measurement of sample mass anchors these predictions. Dynamic mass is crucial for tracking for density, surface tension and viscosity measurement.

## Research impacts

This research aids in dissemination of an baseline archived dataset allowing researchers to validate models accounting for gravity-induced systematic error in property measurement used for industrial welding, casting  and additive manufacturing operations . Industry will be better able to correlate ground and space results to expand the quantity and quality of available information without the requirement for access to space. Advance the understanding of how to best allocate the scant resources available for space-based materials property measurement using levitation.  In the future this could lead to development of a model where fidelity and cost can be readily calculated for a given material classification and serve as the basis for prioritization of specific ground and space thermophysical property investigations.

## Publications (14)

- Uncertainty analysis and performance evaluation of thermophysical property measurement of liquid Au in microgravity
- Electromagnetic levitation containerless processing of metallic materials in microgravity: thermophysical properties
- Quantifying X-ray diffractometer precision for measurement of dislocation density and the evolution of defect structures during solidification of additive manufacturing powders
- Particle size effects on dislocation density, microstructure, and phase transformation for high-entropy alloy powders
- Retained Free Energy with Enhanced Nucleation during Electrostatic Levitation of Undercooled Fe-Co Alloys
- Statistical learning for evaluation of crystal growth in low-melting alloy droplets with application to quasicrystal-forming Ti–Zr–Ni alloys
- Influence of Induced Convection on Transformation Kinetics During Rapid Solidification of Steel Alloys: The Retained Damage Model
- Tracking Evaporation During Levitation Processing of Nickel-Based Superalloys on the ISS
- aximizing scientific return from shared facilities working in space:
ESA's investigator working group for the ISS-EML facility.''
- MHD surrogate model for convection in electromagnetically levitated molten metal droplets processed using the ISS-EML facility.
- Density, excess volume, and structure of Fe–Cr–Ni melts
- A quantitative comparison of thermophysical property measurement of CMSX-4 Plus (SLS) in microgravity and terrestrial environments
- Uncertainty Quantification of Thermophysical Property Measurement in Space and on Earth: A Study of Liquid Platinum Using Electrostatic Levitation
- Thermodynamic assessment of evaporation during molten steel testing onboard the International Space Station

_Rendering of this investigation's entry in `base_de_datos/_todas_las_investigaciones_PSI.json`._