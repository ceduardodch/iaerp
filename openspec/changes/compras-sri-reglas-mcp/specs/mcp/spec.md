## ADDED Requirements

### Requirement: Descubrimiento OAuth de MCP
El proxy público SHALL devolver los metadatos OAuth JSON que anuncia el transporte MCP.

#### Scenario: Cliente sin token
- **WHEN** el cliente recibe el desafío del MCP y consulta su URL de metadatos
- **THEN** recibe el identificador del recurso y el servidor de autorización

#### Scenario: Cliente con permiso de consulta
- **WHEN** el cliente se autentica y pide el catálogo y una consulta permitida
- **THEN** el servidor limita herramientas y resultados a los permisos y al tenant del token
