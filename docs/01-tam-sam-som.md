# TAM, SAM y SOM

## Fecha y fuentes

Estimacion preparada el 2 de julio de 2026. Las cifras deben revisarse al menos
cada seis meses.

Fuentes oficiales:

- INEC, REEM 2025 provisional: 1.204.276 empresas; aproximadamente 1.119.700
  micro, 62.400 pequenas, 9.900 medianas A, 6.900 medianas B y 5.500 grandes.
- INEC, REEM 2024 definitivo: microempresas representan 92,2%; servicios 51,7%
  y comercio 34,1%.
- Superintendencia de Companias: 172.641 companias activas en 2025 y 179.374
  activas reportadas en mayo de 2026.
- SRI: datasets 2025 y 2026 de contribuyentes activos por provincia. Se usaran
  en una validacion posterior para segmentar personas naturales y sociedades.

Enlaces:

- https://www.ecuadorencifras.gob.ec/documentos/web-inec/Estadisticas_Economicas/Registro_Empresas_Establecimientos/2025/Semestre_I/Boletin_REEM_2025.pdf
- https://www.ecuadorencifras.gob.ec/documentos/web-inec/Estadisticas_Economicas/Registro_Empresas_Establecimientos/2024/Semestre_II/Boletin_REEM_2024.pdf
- https://www.supercias.gob.ec/portalscvs/Noticias/Noticias.php?seccion=noticia-130520261
- https://www.sri.gob.ec/en/datasets

## Hipotesis comercial

IAERP se vende por RUC con tres niveles iniciales sujetos a validacion:

| Plan | Precio mensual | Hipotesis de uso |
| --- | ---: | --- |
| Inicial | USD 19 | Microempresa, bajo volumen |
| Gestion | USD 39 | Pyme con cartera y proveedores |
| Automatizacion | USD 79 | Mayor volumen y uso intensivo de IA |

Para dimensionar mercado se usa un ingreso anual promedio hipotetico de USD 348
(USD 29 por mes). No es un precio aprobado.

## TAM

El universo amplio son empresas no grandes del REEM 2025:

`1.119.700 + 62.400 + 9.900 + 6.900 = 1.198.900 empresas`

Con un ingreso anual promedio de USD 348:

`TAM = 1.198.900 x USD 348 = USD 417.217.200 ARR`

Este TAM es estadistico: incluye negocios que no tienen capacidad de compra,
necesidad suficiente o madurez digital.

## SAM

Como proxy conservador se usan las 172.641 companias activas reportadas para
2025 por la Superintendencia:

`SAM inicial = 172.641 x USD 348 = USD 60.079.068 ARR`

La siguiente iteracion debe cruzar datasets del SRI con provincia, actividad,
estado y obligacion de emitir comprobantes electronicos. El foco comercial
inicial sera servicios y comercio, que juntos concentran 85,8% de las empresas
del REEM 2024.

## SOM a tres anos

| Escenario | RUC activos | ARR a USD 348 |
| --- | ---: | ---: |
| Conservador | 500 | USD 174.000 |
| Base | 1.000 | USD 348.000 |
| Expansivo | 2.000 | USD 696.000 |

El objetivo base representa cerca de 0,58% del proxy SAM de companias activas.

## Validaciones pendientes

- Entrevistar al menos 15 pymes de servicios y comercio.
- Medir volumen mensual de comprobantes y tiempo dedicado a cartera/proveedores.
- Validar disposicion de pago para los tres planes.
- Cuantificar costo de email, WhatsApp, almacenamiento y tokens de IA por plan.
- Recalcular SAM con el catastro SRI activo y criterios reproducibles.
- Separar mercado de reemplazo de software y mercado que aun opera en hojas.

Las cifras no deben usarse en material comercial sin mostrar fecha, fuente,
hipotesis de precio y limitaciones.
