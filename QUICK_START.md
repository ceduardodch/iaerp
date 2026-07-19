# 🚀 Quick Start - IAERP Development Guide

**Para retomar trabajo rápido:** Lee este archivo (30 segundos)

---

## 📁 Documentation Structure (4 key files)

```
iaerp/
├── CLAUDE.md              # 🎯 SETUP - Stack, arquitectura, cómo funciona
├── BACKLOG.md             # 📋 SCOPE - Qué vamos a hacer (12 semanas)
├── SPRINT_STATUS.md       # 📊 PROGRESS - Status de sprints, decisiones técnicas  
├── ISSUE_TRACKING.md      # ✅ TASKS - Tareas 1x1 para no perder contexto
└── docs/STATUS.md         # 🏠 TRUTH - Fuente de verdad del proyecto
```

---

## 🔄 Quick Resume (20 seconds)

**¿Qué estás haciendo?**
- Mejorando UI/UX del CRM IAERP (12 semanas)
- Sprint 1: CRM Kanban arrastrable (drag & drop)

**¿Dónde empezar?**
1. Lee `ISSUE_TRACKING.md` → Ver próxima tarea pendiente
2. Lee `SPRINT_STATUS.md` → Contexto técnico del sprint
3. Comienza con TASK-1.1 (Instalar dependencias @dnd-kit)

**¿Cómo continuar entre sesiones?**
- Todo está documentado, solo di "Continuar con Sprint 1"
- Si se acaban tokens, no hay problema: next session → "Revisar ISSUE_TRACKING.md"

---

## 🎯 Sprint 1: CRM Kanban Foundation

**Objetivo:** Pipeline visual tipo Canva con drag & drop

**Próximas 3 tareas:**
1. **TASK-1.1:** Instalar @dnd-kit (15-30 min)
2. **TASK-1.2:** Crear CrmKanban.tsx component (1-2 horas)  
3. **TASK-1.3:** Implementar useKanban hook (1-2 horas)

**Duración estimada:** 5-7 días (13.5 horas técnicas)

---

## 📞 Emergency Commands

**Si no sabes qué hacer:**
```
"Revisar ISSUE_TRACKING.md y BACKLOG.md"
```

**Si quieres continuar trabajo:**
```
"Continuar con Sprint 1 - TASK-X.Y"
```

**Si hay problema técnico:**
```
"Revisar SPRINT_STATUS.md - Decision Log y Riesgos"
```

---

## 🛠️ Technical Context (1 minute)

**Stack actual:**
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS
- Backend: FastAPI + SQLAlchemy + PostgreSQL
- CRM: Básico funcional (leads, activities, pipeline)

**Para añadir:**
- @dnd-kit/core (drag & drop)
- Zustand (state management)
- Framer Motion (animations 60fps)

**Archivos clave:**
- `frontend/src/components/crm/` - CRM actual (LeadsPage, LeadDetailPanel)
- `frontend/src/App.tsx` - Navegación principal
- `backend/app/api/crm.py` - Endpoints CRM existentes

---

## 📊 Progress Overview

**Sprint 1:** 🔵 0/10 tareas completadas (0%)
**Overall:** 🔵 0/9 sprints completados (0%)

**Hitos:**
- [x] Plan completo creado (12 semanas)
- [x] Backlog estructurado por sprints
- [x] Documentación para trabajo 1x1
- [ ] CRM Kanban funcional (próximo objetivo)

---

## ⚡ Quick Actions

**Empezar ahora:**
```bash
cd frontend
npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

**Ver status actual:**
```bash
git status
git log -1 --oneline
docker compose ps
```

**Testing:**
```bash
# Backend
cd backend && uv run pytest tests/ -v

# Frontend  
cd frontend && npm run test:e2e
```

---

## 🎓 Learning Resources

**Para aprender sobre las tecnologías:**
- @dnd-kit: https://docs.dndkit.com/
- Framer Motion: https://www.framer.com/motion/
- Zustand: https://docs.pmnd.rs/zustand/getting-started.html

**Ejemplos de Kanban:**
- Trello clones (referencia UX)
- Notion databases (referencia pipeline visual)
- Linear issue boards (referencia drag & drop)

---

## 🆘 Quick Help

**"No entiendo el proyecto"**
→ Revisar CLAUDE.md (stack, arquitectura, convenciones)

**"No sé qué hacer"**
→ Revisar ISSUE_TRACKING.md (próxima tarea: TASK-1.1)

**"Me quedé sin tokens la vez anterior"**  
→ Revisar SPRINT_STATUS.md (última sección: "Session Context")

**"¿Qué hemos hecho ya?"**
→ Revisar docs/STATUS.md (historial de implementación)

---

## 🎯 Success Indicators

**Sprint 1 completado cuando:**
- [ ] Kanban con 7 columnas funcionando
- [ ] Drag & drop suave a 60fps
- [ ] Cards con avatars, badges, gradients
- [ ] Responsive mobile → desktop
- [ ] E2E tests pasando
- [ ] Deploy staging validado

---

**Última actualización:** 2026-07-19
**Sprint actual:** Sprint 1 - CRM Kanban Foundation
**Próxima tarea:** TASK-1.1 (Instalar @dnd-kit dependencias)

**Para continuar solo di: "Revisar ISSUE_TRACKING.md y continuar con Sprint 1"**