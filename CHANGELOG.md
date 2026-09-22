# Novidades

Cada versão tem um cabeçalho `## versão — data` e uma lista de pontos. A aplicação mostra
aos administradores as entradas mais recentes do que a versão instalada quando procura
atualizações.

## 1.6.6 — 2026-09-22
- Plantão ao fim de semana: o dia abre das 09:00 às 18:00 com as pessoas do sábado e a noite segue até às 09:00.
- Noite de serviço até às 09:00, a começar às 18:00 ao fim de semana.
- Ao fim de semana o mínimo ao balcão conta menos uma pessoa durante o almoço.

## 1.6.5 — 2026-09-21
- Gerar a escala só a partir de um dia (botão ↻ em cada dia).
- Escala separada em balcão, administrativo e extras.
- Horário fixo para o backoffice.
- Piadas do dia em português.

## 1.6.4 — 2026-09-20
- Geração nova: nivela o balcão de segunda a sexta, escala só as «Pessoas ao sábado» e ao domingo apenas o plantão. Sem quotas por turno.
- Bloquear células da escala para nada as alterar até serem desbloqueadas.
- Separador Balcão: quem está ao balcão, hora a hora.
- Banco de horas só conta horas já trabalhadas.

## 1.6.3 — 2026-09-20
- Corrige a atualização dentro do contentor: a partir da segunda atualização o reinício ficava na versão da imagem.
- Definições: escolher a imagem do logótipo voltou a funcionar.

## 1.6.2 — 2026-09-20
- Horas extra: o que passar do mínimo da semana entra no banco de horas e acumula nas semanas seguintes.
- Folga extra do plantão marcada como célula própria, sempre depois da noite de fim de semana; aviso enquanto não estiver marcada.
- Separador Horas: coluna «Horas extra» e relatório dos movimentos do banco de horas ao clicar no valor.
- Atualização dentro do contentor mais robusta, com aviso quando uma versão instalada não consegue arrancar.

## 1.6.1 — 2026-09-20
- Separador Definições: título, subtítulo e logótipo da farmácia; painel de versão e dados passam para lá.
- Verificação automática de novas versões (de 6 horas a mensal), com aviso no topo da página e as novidades de cada versão.
- Menu da conta no canto superior direito, com imagem de perfil (ficheiro ou endereço), e frase do dia debaixo do título.
- Turnos: pessoas necessárias em Seg–Sex, Sáb e Dom; os turnos terminam à hora de fecho e em dia fechado só há plantão.
- Horas nocturnas (22:00–09:00) contam à parte; a noite de serviço soma 3 h e, ao fim de semana, dá uma folga extra na semana seguinte.
- Geração: plantão primeiro, a rodar pela equipa, e toda a gente levada às horas da semana. Deixa de haver máximo de turnos.
- Ficha: «backoffice por defeito» (não trabalha ao fim de semana) e «extra» (horas marcadas dia a dia).
- Menu da célula: horas a menos, baixa médica (também por período) e horas de extra.
- Períodos do dia com outro mínimo ao balcão; a célula mostra as horas trabalhadas do dia.

## 1.6.0 — 2026-09-20
- Horário da farmácia por dia da semana, com encerramento semanal.
- Quem faz a noite de serviço fica de folga no dia seguinte; a noite ao sábado ou domingo dá um dia de folga extra no banco de horas.
- As horas entre as 22:00 e as 09:00 são sempre pagas à parte e não entram no banco de horas.
