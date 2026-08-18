# WenAGI — Production Runbook

Чек-лист перевода проекта из демо в продакшен. Каждый пункт — блокер для TGE.

## 1. Смарт-контракты

- [ ] **Аудит.** Отправить `contracts/src` в 1–2 бюро (Trail of Bits, Spearbit,
      OtterSec, Zellic — по бюджету). Средний срок 2–4 недели. Фиксы —
      повторный обзор.
- [ ] **Invariant-тесты** (добавить в `contracts/test`): сумма сплитов ==
      fee при случайных bps; burnedTotal монотонен; merkle root невозможно
      подменить без owner.
- [ ] **Газ.** Прогнать benchmark `settle()` при 1/100/10K запросах — цель
      < 90k gas на сеттелемент (Base: копейки).
- [ ] **Верификация исходников** на Basescan после деплоя ( solc 0.8.28,
      optimizer 200 runs, evmVersion cancun — как в compile.js ).

## 2. Деплой (Base mainnet)

```bash
# 1. Ключи: DEPLOYER (фондирован ETH), TREASURY/RELAYER/ORACLE — мультисиги (Safe 3/5)
cd contracts
export DEPLOYER_PRIVATE_KEY=0x...
export TREASURY_ADDRESS=0x... RELAYER_ADDRESS=0x... ORACLE_ADDRESS=0x...
npx hardhat run scripts/deploy.js --no-compile --network base
# 2. Распределение supply (по токеномике) через treasury-мультисиг
# 3. Вестинги: TokenVesting.create(...) для команды/инвесторов
# 4. Airdrop: node scripts/airdrop-tree.js airdrop.json && WagiAirdrop.setRoot(...)
```

- [ ] Адреса зафиксированы в `backend/.env` и в конфиге фронтенда.
- [ ] owner всех контрактов → transferred на мультисиг DAO (не EOA!).
- [ ] LP: пул 80/20 (Velodrome/Aerodrome на Base), LP токены в TimeLock 2 года.

## 3. Шлюз (backend)

- [ ] `.env` из `.env.example`, секреты — в менеджере (AWS SM/Vault), не в git.
- [ ] `WAGI_STATE_FILE` — на персистентный том; бэкап раз в час.
- [ ] Docker: `docker build -t wagi-gateway ./backend && docker run -d -p 8080:8080 wagi-gateway`
- [ ] TLS терминация (nginx/Caddy/Cloudflare) перед :8080.
- [ ] **Ончейн-сеттелемент:** заменить демо-ledger на вызовы `settle()` релейер-ключом:
      батчинг (1 tx / 100 запросов), nonce-менеджмент, retry-очередь.
- [ ] Рейт-лимиты: уже встроены (ключи/фаусет); добавить per-key RPS на LB.
- [ ] Мониторинг: /healthz в uptime-провайдер; алерты на 402-rate, latency,
      upstream errors; логи — Loki/CloudWatch.

## 4. Безопасность

- [ ] Релейер-ключ — только в KMS/HSM, ротация 30 дней, policy на адрес
      контракта.
- [ ] Секреты OPENAI_API_KEY изолированы от демо-окружения.
- [ ] Баг-баунти: включить в Immunefi (мин. $5K бюджет) после аудита.
- [ ] Форма клейма: geo-fence (OFAC), чекбокс non-US person, лог согласий.

## 5. Листинги и данные

- [ ] CoinGecko/CMC заявка: контакты, volume, docs, audit links.
- [ ] Дексскринер/Декстулс: обновить логотип, соцсети, теги (AI, Deflationary,
      Base).
- [ ] Пресс-кит: mascot.png, og-banner.png, лого-пак (лежат в backend/public).

## 6. Инцидент-план (первый час)

1. Шлюз лёг → статус-страница + твит «gateway degraded, funds are on-chain
   and safe».
2. Подозрение на эксплойт → пауза: релейер-ключ отозвать (setRelayer(0x0) —
   мгновенная остановка сеттелемента), пин с деталями.
3. Эксплойт подтверждён → контакт аудитора, war-room в Discord, постмортем
   за 72 часа.
