import os
import time
import math
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig
from pipeline import SimpleProductionTokenizer, FractalHoloNetInferencePipeline

# =====================================================================
# Богатый обучающий корпус на русском языке (знания, диалоги, рассуждения, наука, литература)
# =====================================================================
def get_russian_corpus():
    corpus = """
Искусственный интеллект — это комплекс технологических и программных решений, позволяющий имитировать когнитивные функции человека.
Архитектура Fractal-HoloNet построена на принципах комплексного фазового резонанса и фрактальных частотных октав.
В отличие от стандартного механизма внимания трансформеров, имеющего квадратичную сложность O(N^2), Fractal-HoloNet обладает строго линейной сложностью O(N).
Это позволяет обрабатывать колоссальные объемы текстовой информации и непрерывных потоковых данных без задержек.

Голографическая память нейросети сохраняет ассоциации между словами в комплексном пространстве чисел.
Каждое новое слово модулирует фазу колебаний, аккумулируя знания в компактном векторе состояния.
При инференсе память состояния O(1) остается константной, поэтому скорость ответа не падает даже при диалогах длиной в миллионы токенов.

Вопрос: В чем главное преимущество фрактальной архитектуры?
Ответ: Главное преимущество заключается в линейной масштабируемости, высокой скорости генерации и минимальном потреблении оперативной памяти.

Вопрос: Как нейросеть обучается русскому языку?
Ответ: Нейросеть анализирует морфологию, грамматику, структуру предложений и семантические связи между словами с помощью предсказания следующего байта или токена.

Вопрос: Что такое фазовый резонанс?
Ответ: Фазовый резонанс — это интерференция комплексных гармонических колебаний, позволяющая извлекать релевантные факты из памяти за один такт.

Диалог пользователя и ассистента:
Пользователь: Привет! Расскажи, как ты работаешь.
Ассистент: Здравствуйте! Я работаю на базе архитектуры Fractal-HoloNet. Моя память обрабатывает информацию непрерывно и быстро.

Пользователь: Какая сложность вычислений при генерации текста?
Ассистент: Сложность вычислений на каждый сгенерированный токен является константной O(1), что гарантирует мгновенный ответ.

Пользователь: Можешь ли ты работать с датчиками и звуком?
Ассистент: Да, благодаря непрерывному представлению я могу напрямую принимать сырые сигналы без дискретизации.

О науке и технологиях:
Физика описывает законы материального мира через математические уравнения и квантовые состояния.
Математика служит универсальным языком логики, алгоритмов и пространственных преобразований.
Компьютерные науки объединяют структуры данных, теорию сложности и машинное обучение для решения сложных прикладных задач.
Астрономия исследует движение небесных тел, далекие галактики, квазары и реликтовое излучение Вселенной.

Классическая литература и язык:
Мороз и солнце; день чудесный! Еще ты дремлешь, друг прелестный.
Пора, красавица, проснись: открой сомкнуты негой взоры навстречу северной Авроры, звездою севера явись!
У лукоморья дуб зеленый; златая цепь на дубе том: и днем и ночью кот ученый все ходит по цепи кругом.
Идет направо — песнь заводит, налево — сказку говорит. Там чудеса: там леший бродит, русалка на ветвях сидит.

Великий и могучий русский язык обладает богатой лексикой, гибким синтаксисом и развитой системой словообразования.
Каждое слово несет в себе глубокий смысл, эмоциональную окраску и культурное наследие поколений.
""" * 35 # Мультиплицируем для глубокой сходимости эмбеддингов
    return corpus.strip()


class RussianTextDataset(Dataset):
    def __init__(self, token_ids, block_size: int = 96):
        self.block_size = block_size
        self.data = torch.tensor(token_ids, dtype=torch.long)
        
    def __len__(self):
        return max(1, (len(self.data) - 1) // self.block_size)
        
    def __getitem__(self, idx):
        start_idx = idx * self.block_size
        end_idx = start_idx + self.block_size + 1
        chunk = self.data[start_idx:end_idx]
        
        if len(chunk) < self.block_size + 1:
            pad_len = self.block_size + 1 - len(chunk)
            chunk = torch.cat([chunk, torch.zeros(pad_len, dtype=torch.long)])
            
        x = chunk[:-1]
        y = chunk[1:]
        return x, y


def train_russian_language():
    print("=" * 75)
    print("  🇷🇺 ОБУЧЕНИЕ МОДЕЛИ FRACTAL-HOLONET РУССКОМУ ЯЗЫКУ (RUSSIAN PRE-TRAINING)")
    print("=" * 75)
    
    corpus = get_russian_corpus()
    encoded_bytes = corpus.encode("utf-8")
    print(f"📊 Размер обучающего корпуса: {len(corpus):,} символов ({len(encoded_bytes):,} UTF-8 байт)")
    
    tokenizer = SimpleProductionTokenizer()
    tokens = tokenizer.encode(corpus, add_bos=False)
    
    block_size = 96
    batch_size = 64
    dataset = RussianTextDataset(tokens, block_size=block_size)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    
    print(f"📦 Всего обучающих батчей: {len(loader)} (блок {block_size} токенов, batch_size={batch_size})")
    
    config = FractalHoloNetConfig(
        vocab_size=300,
        d_model=128,
        n_layers=4,
        d_ff=384,
        dropout=0.02
    )
    model = ProductionFractalHoloNet(config)
    print(f"⚙️ Параметров архитектуры: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    print("-" * 75)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=0.01)
    criterion = nn.CrossEntropyLoss()
    
    epochs = 5
    save_dir = "./checkpoints/fractal_holonet_base"
    
    start_time = time.time()
    model.train()
    
    for epoch in range(epochs):
        total_loss = 0.0
        batches = 0
        
        for x, y in loader:
            optimizer.zero_grad()
            logits, _ = model(x, states=None, use_step=False)
            loss = criterion(logits.view(-1, logits.size(-1)), y.view(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            total_loss += loss.item()
            batches += 1
            
        avg_loss = total_loss / max(1, batches)
        ppl = math.exp(min(avg_loss, 20))
        print(f"  Эпоха [{epoch+1:02d}/{epochs:02d}] | Train Loss: {avg_loss:.4f} | Perplexity (PPL): {ppl:.2f}")
            
    total_time = time.time() - start_time
    print(f"✅ Обучение русскому языку завершено за {total_time:.2f} сек!")
    
    # Сохраняем модель
    os.makedirs(save_dir, exist_ok=True)
    model.save_pretrained(save_dir)
    tokenizer.save(os.path.join(save_dir, "tokenizer.json"))
    print(f"💾 Обученная русскоязычная модель сохранена в: {save_dir}")
    
    # Комплексное тестирование русскоязычных ответов
    print("\n" + "=" * 75)
    print("  🧪 ТЕСТИРОВАНИЕ РУССКОЯЗЫЧНЫХ ОТВЕТОВ FRACTAL-HOLONET")
    print("=" * 75)
    
    pipe = FractalHoloNetInferencePipeline(save_dir)
    
    prompts = [
        "Искусственный интеллект — это",
        "Архитектура Fractal-HoloNet построена на",
        "Вопрос: В чем главное преимущество фрактальной архитектуры?\nОтвет:",
        "Пользователь: Какая сложность вычислений при генерации текста?\nАссистент:",
        "Мороз и солнце; день чудесный!"
    ]
    
    for p in prompts:
        res = pipe.generate(p, max_new_tokens=100, temperature=0.5, top_k=25, top_p=0.85)
        print(f"\n[ПРОМПТ]:\n{p}")
        print(f"[ОТВЕТ МОДЕЛИ]:\n{res['generated_text']}")
        print(f"[ПОЛНЫЙ ТЕКСТ]:\n{res['full_text']}")
        print("-" * 50)

if __name__ == "__main__":
    train_russian_language()
