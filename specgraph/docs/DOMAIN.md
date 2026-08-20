# Сущности

```
Document
 ├── Product          изделие, дерево parent
 ├── Requirement      текущая ревизия (is_current)
 │     ├── attributes
 │     └── RequirementRevision   старые формулировки
 ├── Attachment       файл к требованию
 └── Illustration     картинка из Word
```

Связи (`entity_relations`): `applies_to`, `composed_of`, `derived_from`, `implements`, `illustrated_by`.

Пайплайн получает **текущие** требования + родителей (даже stub) + текст приложений.
