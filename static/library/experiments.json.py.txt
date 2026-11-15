{
  "fm2": {
    "name": "FM2 - Flammability of Materials on the Moon",
    "ctx": {
      "gravity": "lunar",
      "material": ["fabric"],
      "o2": 34,
      "pressure_kpa": 56.5
    },
    "note": "Studies how materials burn at 1/6 g. Will test 21% O2 at 14.7 psia and 34% at 8.2 psia.",
    "sources": ["fm2", "glenn"]
  },
  "luci": {
    "name": "LUCI - Lunar Combustion Investigation",
    "ctx": {
      "gravity": "lunar",
      "material": ["fabric"]
    },
    "note": "Suborbital rocket that simulates lunar gravity and measures flame spread.",
    "sources": ["luci"]
  },
  "sofie": {
    "name": "SoFIE - Solid Fuel Ignition and Extinction",
    "ctx": {
      "gravity": "micro",
      "topic": ["standard"]
    },
    "note": "Tests the 1 g flammability standard in microgravity.",
    "sources": ["glenn"]
  },
  "flare": {
    "name": "FLARE - Flammability Limits at Reduced-g",
    "ctx": {
      "gravity": "micro",
      "topic": ["standard"]
    },
    "note": "Seeks to relate 1 g flammability limits to low-gravity ones.",
    "sources": ["glenn", "flare2021"]
  },
  "saffire": {
    "name": "Saffire - Large-Scale Spacecraft Fires",
    "ctx": {
      "gravity": "micro",
      "ventilation": "none",
      "topic": ["gas"]
    },
    "note": "Fires of up to ~10 kW in uncrewed spacecraft.",
    "sources": ["saffire45", "saffire6"]
  },
  "cir": {
    "name": "CIR - Combustion Integrated Rack (ISS)",
    "ctx": {
      "gravity": "micro",
      "ignition": ["electrical"]
    },
    "note": "ISS combustion rack with a 100 L chamber.",
    "sources": ["glenn"]
  }
}