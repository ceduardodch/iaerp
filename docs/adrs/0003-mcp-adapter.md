# ADR 0003: MCP como adaptador de casos de uso

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

IAERP debe funcionar desde la web y agentes externos sin duplicar reglas ni
exponer acceso generico a datos.

## Decision

Publicar `/mcp` con Streamable HTTP, OAuth 2.1 y SDK oficial Python estable
`>=1.27,<2`. Cada tool llama un comando/consulta existente, usa schemas cerrados
y devuelve resultado estructurado.

## Consecuencias

- REST, workers y MCP comparten comportamiento.
- No se ofrecen SQL, codigo o filesystem genericos.
- Cambios incompatibles en tools requieren version/deprecacion.
