# 🤖 WenAGI — $WAGI

> **WEN AGI?** — старейший вопрос крипты получил ответ: живой прогресс-бар.
> $WAGI — токен для децентрализованного LLM-инференса: каждый промпт
> оплачивается токенами, **5% каждой комиссии сжигается навсегда**, а сожжённое
> двигает общий прогресс до AGI.

```
Агент/приложение ──► WenAGI Gateway (OpenAI-совместимый API)
                          │  биллинг в $WAGI
                          ▼
                 InferenceMarket.sol (Base)
                 ├─ 80% GPU-провайдеру
                 ├─ 15% DAO-казне
                 └─ 5% BURN ──► AGIProgressOracle: 0…100% «wen AGI?»
```

## Почему это может завируситься

1. **Живой AGI-прогресс-бар** — один общий счётчик интернета («мы на 7.3%»).
2. **Карточка прогресса** — PNG «мои промпты сожгли N $WAGI» (Wrapped × crypto).
3. **Стена промптов** — публичная анонимная лента запросов сети.
4. **Burn как ритуал** — использование ИИ физически уменьшает supply.
5. **Имя** — «wen AGI?» крипта говорит уже 10 лет; мы просто выпустили тикер.

## Структура репозитория

| Папка | Что внутри |
|---|---|
| `contracts/` | 5 смарт-контрактов (Solidity 0.8.28) + **21 тест** (Hardhat 3 + viem) |
| `backend/` | WenAGI Gateway: OpenAI-совместимый API с биллингом $WAGI, **9 тестов**, zero-deps |
| `backend/public/` | Лендинг с живым прогресс-баром + плейграунд |
| `marketing/` | Вайтпейпер RU/EN, план запуска, контент-кит, аирдроп, мем-пак, пресс-релиз, KPI |
| `docs/PRODUCTION.md` | Ранбук продакшена: аудит, деплой на Base, инциденты |

## Быстрый старт

```bash
# 1) Контракты: компиляция и тесты
cd contracts && npm install && npm run compile && npm test

# 2) Шлюз + лендинг (zero-dependency)
cd ../backend && npm start
#    → http://localhost:8080        лендинг с живым баром
#    → http://localhost:8080/app.html   плейграунд (демо-ключ, фаусет)

# 3) Тесты шлюза
npm test
```

### API за 30 секунд

```bash
KEY=$(curl -s -X POST localhost:8080/api/keys -d '{}' \
  -H 'content-type: application/json' | jq -r .apiKey)

curl -s localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  -d '{"model":"wagi-1","messages":[{"role":"user","content":"wen agi?"}]}'
```

Ответ — формат OpenAI + блок `wagi: { fee, split, balance, progressBps }`.
Хочешь реальные модели — задай `OPENAI_API_KEY` в `.env` (см. `.env.example`).

## Контракты

| Контракт | Назначение |
|---|---|
| `WagiToken.sol` | ERC-20, fixed 1B, burn, EIP-2612 permit |
| `InferenceMarket.sol` | сеттелемент запросов: 80/15/5, replay-защита, только hash промпта на цепи |
| `AGIProgressOracle.sol` | 10 эпох прогресса по кумулятивному burn; нельзя откатить больше 1% |
| `WagiAirdrop.sol` | merkle-аирдроп, double-claim невозможен |
| `TokenVesting.sol` | линейный вестинг с клиффом, revocable |

Деплой (testnet → mainnet): `docs/PRODUCTION.md`.

## Статус

- ✅ Контракты: написаны, скомпилированы, 21/21 тестов зелёные
- ✅ Шлюз: работает (демо-модель WAGI-1, опциональный real-upstream)
- ✅ Лендинг + плейграунд: живые
- ✅ Маркетинг: полный кит готов к запуску
- ⬜ Аудит → деплой на Base → TGE (по плану `marketing/launch-plan.md`)

## Дисклеймер

Демонстрационный проект. Ничего здесь не является финансовой рекомендацией.
NFA / DYOR.
