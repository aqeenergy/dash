# Datos de combustión del NASA PSI: guía para la IA del equipo

Reto: NASA Space Apps 2026, "Flame in Freefall". Fuente: NASA Physical Sciences Informatics (https://psi.nasa.gov/physci/repo). Licencia: CC0-1.0. En la app hay que citar el DOI de cada investigación, que viene en su fichero de metadatos.

## Estructura que crea `descargar_psi.sh`

```
psi_datos/
├── metadatos/
│   ├── _todas_las_investigaciones_PSI.json   listado de las 133 investigaciones del PSI
│   └── PSI-XX.json                           ficha completa de cada una de las 24 de combustión
├── tablas/PSI-XX/                            tablas experimentales (CSV) y matrices de ensayo (XLSX/XLS)
├── telemetria/PSI-XX/                        solo con --todo: series temporales SAME-R y Saffire-III
└── registro_descarga.tsv                     resultado de cada fichero y verificación SHA-256
```

Cada ficha `PSI-XX.json` contiene título, DOI, objetivos, enfoque, hipótesis, hardware, fechas, investigadores, publicaciones y lista de ficheros. Es la base para el ranking y para el RAG.

## Las 24 investigaciones

| Accesión | Investigación | Tipo de combustible | Hardware | Datos tabulares |
|---|---|---|---|---|
| PSI-10 | ACME Flame Design | Llamas gaseosas esféricas (normales e inversas) | CIR / ACME | 2 tablas por ensayo ★★★ |
| PSI-20 | ACME BRE (Burning Rate Emulator) | Gas que emula sólidos | CIR / ACME | Tabla resumen |
| PSI-21 | ACME CLD Flame | Llama laminar de difusión en coflujo | CIR / ACME | Tabla resumen |
| PSI-22 | ACME E-FIELD Flames | Llamas con campo eléctrico (análogo a gravedad parcial) | CIR / ACME | Tabla resumen |
| PSI-23 | ACME s-Flame | Llamas esféricas | CIR / ACME | Tabla resumen |
| PSI-159 | ACME CFI-G | Llamas frías gaseosas, hasta un 85 % de O₂ | CIR / ACME | 2 tablas por ensayo ★★★ |
| PSI-69 | FLEX | Gotas (metanol, heptano…), supresión con CO₂/He | CIR / MDCA | Tabla de unos 274 ensayos ★★★ |
| PSI-68 | FLEX-2 | Gotas, mezclas de combustibles | CIR / MDCA | Tabla de rangos |
| PSI-39 | CFI | Llamas frías en gotas | CIR / MDCA | Tabla |
| PSI-26 | BASS | Sólidos (PMMA, tejidos…) con flujo | MSG / conducto SPICE | Tabla + matriz XLSX ★★ |
| PSI-25 | BASS-II | Sólidos con flujo de 0 a 53 cm/s | MSG / conducto SPICE | Tabla + matriz XLSX ★★★ |
| PSI-107 | SPICE | Punto de humo en llamas de chorro | MSG | Tabla |
| PSI-60 | Análisis de datos de SPICE | Estudio de tierra | — | Sin tabla en la lista |
| PSI-106 | SLICE | Despegue de llamas de chorro | MSG | Tabla |
| PSI-98 | Saffire-I | Incendio grande de tejido en Cygnus | Cygnus | Tabla |
| PSI-99 | Saffire-II | 15 muestras de materiales | Cygnus | Tabla |
| PSI-100 | Saffire-III | Incendio grande + telemetría a 1 Hz | Cygnus | Tabla + telemetría (--todo) |
| PSI-102 | SAME | Humo de materiales sobrecalentados | MSG | Tabla + log de ensayo XLS |
| PSI-101 | SAME-R | Respuesta de detectores de humo | MSG | Log de ensayos + 44 CSV de telemetría (--todo) ★★★ detección |
| PSI-115 | Uso de los datos de SAME | Estudio de tierra | — | Sin tabla en la lista |
| PSI-47 | DAFT | Polvo y aerosoles (falsas alarmas) | — | Tabla |
| PSI-62 | Modelado FGM de propagación concurrente | Estudio de tierra (BASS) | — | Sin tabla en la lista |
| PSI-117 | Perturbación termo-convectiva en llamas frías | Estudio de tierra | — | Sin tabla en la lista |
| PSI-142 | Transiciones de llamas frías | Estudio de tierra | — | Tabla resumen |

## Avisos para la IA (validez científica)

- **No inventar valores.** Celda vacía es "no disponible", nunca cero.
- **Codificación.** Algunos CSV del PSI vienen en Windows-1252, no en UTF-8. Si salen caracteres raros, leed con `encoding="cp1252"`.
- **Rangos.** En FLEX, el O₂ va de 0,12 a 0,34 y el CO₂ de 0 a 0,70 en fracción molar. Fuera de ahí, cualquier predicción es extrapolación.
- **Colinealidad.** O₂ + CO₂ + N₂/He ≈ 1, así que no son variables independientes.
- **Gravedad parcial.** El PSI no tiene datos de gravedad lunar ni marciana. Todo lo que se diga para la Moon Base (≥30 % O₂, ≤10,2 psi) es hipótesis acotada entre 0 g y 1 g.
- **Trazabilidad.** Cada respuesta de la IA debería citar accesión, DOI y nombre de fichero.
- **SHA-256 "NO".** Si `registro_descarga.tsv` marca "NO", el fichero se bajó bien pero difiere de la versión del 8-11-2026 (el PSI puede haberlo actualizado). Hay que revisarlo, no descartarlo.
- **Vídeos.** Los vídeos y archivos grandes (BASS-II .mp4, imágenes de SPICE…) no están incluidos. Se bajan a mano desde la web del PSI si hacen falta para visión por computador. Las peticiones de más de 1 GB llegan por correo.
