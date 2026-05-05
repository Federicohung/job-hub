# 🦞 Job Hub API

Data hub de vacantes del mercado hispano. Actualizado automáticamente cada 6 horas via GitHub Actions.

## Endpoints para consumir

### JSON directo (recommended)
```
https://raw.githubusercontent.com/Federicohung/job-hub/master/scraper/data/jobs.json
```

### Webhook / Fetch
Tu sistema puede hacer un simple `GET` a esa URL cada vez que necesite los datos.

### Stats rápidos
```python
import requests
data = requests.get("https://raw.githubusercontent.com/Federicohung/job-hub/master/scraper/data/jobs.json").json()

print(f"Total: {data['totalJobs']}")
print(f"Remote Spanish: {data['breakdown']['remote-spanish']}")
print(f"Remote LATAM: {data['breakdown']['remote-latam']}")
print(f"Remote Spain: {data['breakdown']['remote-spain']}")
print(f"Fuentes: {data['sources']}")
```

## Filtros disponibles en el JSON

Cada job tiene:
- `locationPriority`: remote-spanish, remote-latam, remote-spain, remote-global, hybrid-latam, hybrid-spain, onsite-latam, onsite-spain
- `locationTier`: 1-9 (1 = mejor prioridad)
- `source`: remotive, arbeitnow, remoteok, torre
- `remote`: boolean
- `urlValid`: boolean (link verificado)
- `tags`: array de keywords

## Priorización

1. 🌐 Remote Spanish-speaking
2. 🌎 Remote LATAM
3. 🇪🇸 Remote Spain
4. 🌍 Remote Global
5. 🏢 Hybrid LATAM
6. 🏢 Hybrid Spain
7. 📍 On-site LATAM
8. 📍 On-site Spain

## Refresh

- **Automático**: Cada 6 horas (GitHub Actions cron)
- **Manual**: Actions tab → "Run workflow"
