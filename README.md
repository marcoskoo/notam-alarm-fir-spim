# NOTAM ALARM — FIR SPIM

Sistema de monitoreo y alarmas de NOTAMs en tiempo real para la FIR SPIM (Lima, Perú).

## Características

- **133+ NOTAMs** cargados automáticamente desde CORPAC S.A.
- **Auto-refresh cada 1 minuto** — datos siempre actualizados
- **Alarmas auditivas** para NOTAMs que vencen en <10 minutos
- **Filtros**: Todos / Con EST / Sin EST / PERM
- **Búsqueda**: por aeródromo, código Q, texto, o número de NOTAM

## API Endpoints

| Endpoint | Descripción |
|----------|-------------|
| `GET /` | Aplicación web |
| `GET /notams` | Todos los NOTAMs |
| `GET /notams/{id}` | NOTAM específico |
| `GET /notams/type/{type}` | Filtrar por tipo |
| `GET /notams/serie/{serie}` | Filtrar por serie |
| `POST /refresh` | Actualizar datos desde CORPAC |

## Deploy en Railway

1. Crear cuenta en [railway.app](https://railway.app)
2. Conectar repositorio de GitHub
3. Railway detectará automáticamente la configuración
4. Deploy automático

## Desarrollo local

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Fuente de datos

- **CORPAC S.A.** — [appoperacional.corpac.gob.pe](https://appoperacional.corpac.gob.pe/NOTAM/)
- FIR SPIM (Lima, Perú)
- NOTAMs Vigentes

## Tecnologías

- **Backend**: Python, FastAPI, Uvicorn
- **Frontend**: HTML5, CSS3, JavaScript vanilla
- **Scraping**: Playwright + Chromium
- **Deploy**: Railway
