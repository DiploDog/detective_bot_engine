сначала читать relevant docs/code;
не менять engine/game semantics без необходимости;
не делать game-specific branches;
не начинать следующий этап;
не добавлять технологии вне scope;
real PostgreSQL для DB integration tests;
полный pytest в конце;
validators;
legacy не менять;
если обнаружен architectural gap — STOP и сообщить;
минимальный diff, без unsolicited refactoring.