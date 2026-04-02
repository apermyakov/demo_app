# Karaoke Alignment: Design & Technology Choice

## Задача

Получить точные таймкоды для каждого слова (word-level) или строки (line-level) из mp3 + текста песни на русском языке. Результат используется для караоке-overlay в клипе.

---

## Сравнение вариантов

### 1. Whisper + Forced Alignment (✅ РЕКОМЕНДУЕТСЯ)

**Pipeline:**
1. **Vocal separation** (опционально): Demucs/MDX-Net отделяет вокал от инструментов
2. **Whisper large-v3** транскрибирует вокал с word-level timestamps
3. **Forced alignment** (whisper-timestamped или NeMo) — выравнивает предоставленный текст по аудио
4. Post-processing: smoothing, gap filling, syllable merging

**Плюсы:**
- Whisper отлично работает с русским языком
- Word-level timestamps из коробки
- Forced alignment корректирует расхождения между текстом и вокалом
- Self-hosted, предсказуемая стоимость
- Хорошо работает на пении (не только speech)

**Минусы:**
- Whisper может "галлюцинировать" на длинных инструментальных паузах
- Качество падает на сильно обработанном вокале (autotune, heavy reverb)
- Нужен GPU (но inference быстрый: ~30 сек на 3-минутный трек)

**Стоимость:** $0.01–$0.03 за клип (self-hosted GPU)

### 2. Gentle / Montreal Forced Aligner (MFA)

**Pipeline:**
1. Vocal separation
2. MFA с русской акустической моделью
3. Phoneme-level → word-level aggregation

**Плюсы:**
- Точный forced alignment
- Работает с предоставленным текстом (не нужна транскрипция)

**Минусы:**
- Русская модель MFA менее зрелая, чем Whisper
- Требует подготовки произношения (lexicon)
- Хуже работает на пении vs речи
- Более сложная настройка

**Стоимость:** $0.01–$0.02 за клип

### 3. Cloud ASR APIs (Google Speech, Azure, AssemblyAI)

**Плюсы:**
- Managed, не нужен свой GPU
- Хорошее качество на речи

**Минусы:**
- Word-level timestamps на пении нестабильны
- Стоимость $0.006–$0.024 за минуту → $0.02–$0.07 за 3-минутный трек
- Зависимость от внешнего API
- Русский язык поддерживается, но не приоритет
- Нет forced alignment с предоставленным текстом

**Стоимость:** $0.02–$0.07 за клип

### 4. Hybrid: Whisper transcribe + NeMo/CTC forced alignment

**Pipeline:**
1. Vocal separation (Demucs)
2. Whisper transcribe → получить грубые таймкоды
3. NeMo CTC forced alignment → выровнять предоставленный текст
4. Merge: использовать NeMo таймкоды с Whisper как fallback

**Плюсы:**
- Максимальная точность
- Двойная проверка

**Минусы:**
- Двойной compute
- Сложность pipeline

**Стоимость:** $0.03–$0.05 за клип

---

## Решение для MVP

### Primary: Whisper large-v3 + whisper-timestamped

```
Input: vocals.wav (after Demucs separation) + lyrics.txt
→ whisper-timestamped с параметром --word_timestamps
→ forced alignment с предоставленным текстом
→ post-processing
→ alignment.json
```

### Fallback chain:
1. **Word-level** (primary) — whisper-timestamped
2. **Line-level** (fallback 1) — если word confidence < 0.5, группируем в строки
3. **Even-split** (fallback 2) — если alignment полностью провалился, равномерно раскидываем строки по длительности аудио

---

## Vocal Separation

**Рекомендация: Demucs v4 (htdemucs)**

Зачем:
- Убирает инструменты → Whisper точнее распознаёт слова
- Особенно важно для songs с тяжёлой аранжировкой
- Latency: ~15 сек на 3-минутный трек (GPU)
- Self-hosted, бесплатно

Когда пропускать:
- Если вокал уже чистый (a cappella)
- Если нужно сэкономить 15 сек latency (флаг skip_separation)

---

## Формат выходного JSON

```json
{
  "version": "1.0",
  "song_id": "abc123",
  "duration": 180.5,
  "language": "ru",
  "alignment_method": "whisper_forced",
  "confidence": 0.87,
  "segments": [
    {
      "index": 0,
      "line": "С днём рождения тебя",
      "start": 12.34,
      "end": 15.67,
      "confidence": 0.92,
      "words": [
        {"word": "С", "start": 12.34, "end": 12.50, "confidence": 0.95},
        {"word": "днём", "start": 12.50, "end": 13.10, "confidence": 0.91},
        {"word": "рождения", "start": 13.10, "end": 14.40, "confidence": 0.89},
        {"word": "тебя", "start": 14.40, "end": 15.67, "confidence": 0.93}
      ]
    },
    {
      "index": 1,
      "line": "",
      "start": 15.67,
      "end": 24.00,
      "is_instrumental": true,
      "words": []
    }
  ]
}
```

### Поля:
- `confidence` — уровень уверенности (0–1), ниже 0.5 → используем line-level fallback
- `is_instrumental` — пустой сегмент (проигрыш)
- `words[].start/end` — в секундах, float
- `segments[].line` — полная строка для line-level отображения

---

## Edge Cases и решения

### 1. Текст не совпадает с записью
**Проблема:** Исполнитель импровизирует, добавляет/пропускает слова.
**Решение:**
- Whisper транскрибирует реальный вокал
- Forced alignment находит best match между предоставленным текстом и транскрипцией
- Неопознанные слова помечаются `confidence: 0` → отображаются по строкам
- Метрика: Levenshtein distance между lyrics и transcription → если > 30%, warning

### 2. Распевание слогов
**Проблема:** "Лю-ю-ю-бовь" — один слог длится 2 секунды.
**Решение:**
- word.end - word.start > 1.5 сек → помечаем `"extended": true`
- Караоке renderer делает progressive highlight внутри слова
- Визуально: слово подсвечивается плавно слева направо

### 3. Бэк-вокал
**Проблема:** Demucs может подмешать бэки в основной вокал.
**Решение:**
- В MVP игнорируем: показываем только основной текст
- Бэки не влияют на alignment, т.к. мы делаем forced alignment по предоставленному тексту
- В будущем: отдельная дорожка для бэков

### 4. Повторяющиеся строки (припев)
**Проблема:** "Ла-ла-ла" повторяется 4 раза.
**Решение:**
- Forced alignment привязывает каждый экземпляр к конкретному месту в аудио
- `segment.index` позволяет различать повторения
- В lyrics предоставляем полный текст со всеми повторами

### 5. Word-level неточный
**Проблема:** Whisper даёт ±200ms ошибку на слово.
**Решение:**
- Для караоке ±200ms приемлемо (человек не замечает)
- Smoothing: если gap между словами < 100ms → убираем gap
- Если word.confidence < 0.4 → переключаемся на line-level для этого сегмента
- Line-level всегда стабильный fallback

---

## Рекомендуемая архитектура alignment worker

```
alignment_worker/
├── demucs_separator.py    # vocal separation
├── whisper_aligner.py     # whisper + forced alignment
├── postprocessor.py       # smoothing, gap filling, confidence filtering
├── fallback.py            # line-level и even-split fallbacks
├── schemas.py             # Pydantic models для alignment JSON
└── worker.py              # queue consumer, orchestration
```

**Runtime:**
- GPU: NVIDIA T4 или L4 (достаточно для Whisper large-v3 + Demucs)
- RAM: 8 GB
- Latency: 30–60 сек на 3-минутный трек
- Throughput: ~60 tracks/hour на 1 GPU
