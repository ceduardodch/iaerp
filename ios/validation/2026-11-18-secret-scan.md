# Revisión de falsos positivos del cliente iOS

El escaneo local con detect-secrets 1.5.0 identificó doce valores públicos o
sintéticos: seis en archivos nativos y seis de procedencia de skills. La revisión
añade sólo doce entradas por ruta, tipo y hash a
`.secrets.baseline`, con `is_false_positive: true`. No cambia plugins, filtros,
fuentes Swift, aserciones ni permisos.

| Archivo y línea | Evidencia |
| --- | --- |
| `IAERP.xcodeproj/xcshareddata/xcschemes/IAERP.xcscheme:18` | `BlueprintIdentifier` del target IAERP; coincide con PBXNativeTarget en `project.pbxproj:269`. Es una referencia de compilación. |
| Mismo scheme, línea 32 | Target IAERPAppTests; coincide con `project.pbxproj:248`. |
| Mismo scheme, línea 46 | Target IAERPUITests; coincide con `project.pbxproj:230`. |
| `Package.swift:13` | Revisión fijada del repositorio público [openid/AppAuth-iOS](https://github.com/openid/AppAuth-iOS); coincide con `Package.resolved:9`. Identifica código de una dependencia; no autentica. |
| `Tests/IAERPClientTests/ERPClientTests.swift:167` | URL sintética con usuario y clave de ejemplo en un host `.invalid`. `insecureConfigurationRejected` exige error `invalidConfiguration`. |
| `Tests/IAERPIdentityTests/IdentityTests.swift:38` | URL sintética equivalente para OIDC. `refusesUnsafeURLs` exige error `invalidConfiguration`. |

Todas las rutas de la tabla son relativas a `ios/IAERP/`. Las dos URL prueban
el rechazo de credenciales incrustadas; no son accesos reales y se conservan
sin codificar ni quitar las aserciones.

Comando del hook, con el mismo conjunto de archivos nuevos del incremento
(más este documento):

```sh
git ls-files --others --exclude-standard -z -- ios .github/workflows/ios.yml \
  docs/adrs/0022-native-ios-client.md docs/adrs/0023-ios-saved-accounts.md \
  docs/adrs/0025-ios-durable-draft-recovery.md docs/backlog/ios-backlog.md |
  xargs -0 uvx --offline --python 3.12 --from detect-secrets==1.5.0 \
  detect-secrets-hook --no-verify --baseline .secrets.baseline
```

Resultado: **78 archivos, salida 0**. Como la baseline editada aún no estaba en
staging, el hook directo pidió `git add .secrets.baseline`. La validación usó
una copia idéntica de esa baseline en un archivo temporal; no cambió el índice
compartido. El comando anterior sirve cuando el responsable prepare el commit.
`--no-verify` evita comprobaciones de credenciales por red; `--offline` evita
descargas de la herramienta.

La excepción queda ligada al valor detectado dentro de cada archivo. Un valor
distinto no hereda la excepción. Se comprueba además con canarios sintéticos
en una copia temporal de esas mismas rutas, sin tocar las fuentes del proyecto
ni consultar servicios externos. El escaneo no demuestra la ausencia de todo
secreto; conserva los detectores y límites existentes. En ese control, las cuatro
rutas con valores originales dieron salida 0; tras añadir un canario de token
sintético distinto a cada una, el hook dio salida 1 y señaló las cuatro rutas.

## Procedencia de los tres skills Swift

El escaneo completo de archivos seguidos por Git señaló seis huellas más en
`skills-lock.json`. `sourceRef` fija una revisión del repositorio público;
`computedHash` es SHA-256 de los bytes de `SKILL.md`, como declara `hashScope`.
No es un hash de la carpeta completa ni una credencial.

| Líneas de `skills-lock.json` | Procedencia |
| --- | --- |
| 49 y 51 | `swiftui-expert-skill`, [AvdLee/SwiftUI-Agent-Skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) |
| 58 y 60 | `swift-concurrency`, [AvdLee/Swift-Concurrency-Agent-Skill](https://github.com/AvdLee/Swift-Concurrency-Agent-Skill) |
| 67 y 69 | `swift-testing-expert`, [AvdLee/Swift-Testing-Agent-Skill](https://github.com/AvdLee/Swift-Testing-Agent-Skill) |

Se recalcularon las tres huellas desde los archivos instalados en
`~/.codex/skills/<skill>/SKILL.md`: coinciden con el lock. También coinciden con
las copias locales revisadas al instalarlos. La comprobación fue local; no se
descargaron ni actualizaron skills y no se cambió `skills-lock.json`.

La comprobación completa usa `git ls-files -z` en vez de la lista inicial de
archivos nuevos, con el mismo hook y versión anteriores. Como el nuevo ajuste
de baseline aún no está en staging, se usan copias idénticas de los archivos
seguidos en un repositorio temporal, incluida la baseline en su ruta habitual.
Así se conserva su filtro estándar y no cambia el índice compartido.
Resultado: **712 archivos, salida 0**, con detect-secrets 1.5.0, `--offline` y
`--no-verify`. La copia temporal ocupó unos 8.2 MiB y se retiró al terminar.
Se incluye un control negativo con
una copia temporal de `skills-lock.json`: sus huellas originales pasan y un
canario sintético nuevo se rechaza con salida 1 en esa misma ruta. No se amplían
filtros ni se excluye el archivo.
