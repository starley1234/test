# WenAGI — Production Runbook

Чек-лист перевода проекта из демо в продакшен. Каждый пункт — блокер для TGE.

## 1. Смарт-контракты

- [ ] **Аудит.** Отправить `contracts/src` в 1–2 бюро (Trail of Bits, Spearbit,
      OtterSec, Zellic — по бюджету). Средний срок 2–4 недели. Фиксы —
      повторный обзор. В скоуп обязательно включить `WagiMultisig.sol` —
      теперь это ключевой контракт управления.
- [ ] **Invariant-тесты** (добавить в `contracts/test`): сумма сплитов ==
      fee при случайных bps; burnedTotal монотонен; merkle root невозможно
      подменить без owner.
- [ ] **Газ.** Прогнать benchmark `settle()` при 1/100/10K запросах — цель
      < 90k gas на сеттелемент (Base: копейки).
- [ ] **Верификация исходников** на Basescan после деплоя ( solc 0.8.28,
      optimizer 200 runs, evmVersion cancun — как в compile.js ).

## 2. Мультисиг-кошельки и деплой (Base mainnet)

### 2.1 Церемония ключей (до деплоя)

Каждый signer генерирует ключ АППАРАТНО (Ledger/Trezor) и передаёт адрес
через отдельный канал (сигнатура в закрепе + видеозвонок для сверки):

| Кошелёк | Схема | Роль | Почему так |
|---|---|---|---|
| **TreasuryMultisig** | 3/5 | DAO: владелец всех контрактов, получает 15% комиссий, распределяет supply | деньги двигаются медленно и публично |
| **RelayerMultisig** | 2/3 | сеттлемент батчей `settle()`, ротация операционного ключа | скорость операций при контроле 2 сторон |
| **OracleMultisig** | 2/3 | обновления AGI-прогресса | редкие, но публичные действия |

Альтернатива: Safe (safe.global) — для очень большой казны допустимо
заменить TreasuryMultisig на Safe 4/7; адреса взаимозаменяемы, код менять не нужно.

### 2.2 Деплой

```bash
cd contracts
export DEPLOYER_PRIVATE_KEY=0x...   # фондирован ETH, после деплоя не нужен
export MULTISIG_OWNERS_TREASURY=0xT1,0xT2,0xT3,0xT4,0xT5   MULTISIG_REQUIRED_TREASURY=3
export MULTISIG_OWNERS_RELAYER=0xR1,0xR2,0xR3              MULTISIG_REQUIRED_RELAYER=2
export MULTISIG_OWNERS_ORACLE=0xO1,0xO2,0xO3               MULTISIG_REQUIRED_ORACLE=2
npx hardhat run scripts/deploy.js --no-compile --network base
```

Скрипт: (1) деплоит три `WagiMultisig`, (2) разворачивает всю панораму
с привилегиями ТОЛЬКО у мультисигов, (3) передаёт ownership всех контрактов
на TreasuryMultisig. На live-сетях скрипт отказывается работать без явных
переменных владельцев — случайные EOA-владельцы исключены конструктивно.

### 2.3 Операции через мультисиги

```bash
# submit + автоподпись первым владельцем:
npx hardhat run scripts/exec-via-multisig.js --no-compile --network base -- \
  --multisig 0xTREASURY_MS --dest 0xMARKET --artifact InferenceMarket \
  --fn registerProvider --args '["0xGpuNode"]'
# подписи остальных владельцев (каждый своим ключом):
... -- --multisig 0xTREASURY_MS --confirm --tx-id 0
# исполнение (может любой — газ спонсирует бот):
... -- --multisig 0xTREASURY_MS --execute --tx-id 0
```

### 2.4 Распределение supply и финал

- [ ] Распределение по токеномике: `token.transfer(...)` через TreasuryMultisig
- [ ] Вестинги: `TokenVesting.create(...)` через TreasuryMultisig (казна фондирует контракт)
- [ ] Airdrop: `node scripts/airdrop-tree.js airdrop.json` → `WagiAirdrop.setRoot(...)` через TreasuryMultisig

- [ ] Адреса зафиксированы в `backend/.env` и в конфиге фронтенда.
- [x] owner всех контрактов — TreasuryMultisig (deploy.js делает это автоматически).
- [ ] сверить owners трёх мультисигов на Basescan после деплоя (pk-фингерпринты).
- [ ] LP: пул 80/20 (Velodrome/Aerodrome на Base), LP токены в TimeLock 2 года.

## 3. Шлюз (backend)

- [ ] `.env` из `.env.example`, секреты — в менеджере (AWS SM/Vault), не в git.
- [ ] `WAGI_STATE_FILE` — на персистентный том; бэкап раз в час.
- [ ] Docker: `docker build -t wagi-gateway ./backend && docker run -d -p 8080:8080 wagi-gateway`
- [ ] TLS терминация (nginx/Caddy/Cloudflare) перед :8080.
- [ ] **Ончейн-сеттелемент:** заменить демо-ledger на вызовы `settleBatch()`
      релейер-ключом (до 100 запросов одной транзакцией, атомарно; батч с
      невалидной записью откатывается целиком и ретраится), nonce-менеджмент,
      retry-очередь.
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
