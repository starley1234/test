# WenAGI Gateway

OpenAI-совместимый шлюз LLM-инференса с биллингом в $WAGI.

- **Zero runtime dependencies** (только Node ≥ 18 стандартной библиотеки)
- `POST /v1/chat/completions` — формат OpenAI + блок `wagi` (fee/split/balance)
- `POST /api/keys` — демо-ключ со стартовым балансом
- `POST /api/faucet` — пополнение демо-баланса
- `GET /api/stats` — supply/burned/progress/eras для лендинга
- `GET /api/wall` — публичная анонимная стена промптов (санитизация email/телефонов)
- `GET /healthz` — healthcheck
- Статика: `/` (лендинг), `/app.html` (плейграунд)

Env — см. `.env.example`. Продакшен-ранбук — `../docs/PRODUCTION.md`.

```bash
npm test   # 9 тестов
npm start  # http://localhost:8080
```
