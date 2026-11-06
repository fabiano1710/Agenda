# Nossa Agenda — agenda familiar PWA

Projeto **independente** do sistema Horta Pedidos, com **novo repositório, novo serviço Railway e novo banco PostgreSQL**. Mantém a stack FastAPI/SQLAlchemy/PostgreSQL do projeto de referência; não reutiliza credenciais nem altera a horta.

## Funcionalidades
- Dois membros com contas e senhas individuais, criadas no primeiro início via variáveis de ambiente.
- Dashboard compartilhado, filtros por membro, datas em ordem crescente, contadores de pendentes/hoje/concluídos.
- Criar, alterar, excluir e concluir/reabrir compromissos. Concluídos somem da visão principal e ficam no histórico pesquisável.
- Pesquisa por título, detalhes, categoria, pessoa, local e data; filtros pendentes, concluídos e todos.
- Categorias, observações, localização, horário de término e lembrete configurável por compromisso.
- Seis temas de cor por usuário, responsividade desktop/mobile e PWA instalável.
- Web Push com consentimento do dispositivo, via VAPID. Necessita configuração das chaves e HTTPS. Lembretes são enviados apenas ao membro responsável.

## Executar localmente
1. Instale Python 3.12 e `pip install -r requirements.txt`.
2. Defina `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PARTNER_EMAIL`, `PARTNER_PASSWORD` e `SECRET_KEY` no ambiente. Use senhas distintas de pelo menos 10 caracteres.
3. Defina `COOKIE_SECURE=0` para teste em HTTP local.
4. Rode `uvicorn app.main:app --reload` e acesse `http://localhost:8000`.
5. Sem `DATABASE_URL`, somente **desenvolvimento local** usa SQLite. Para produção configure PostgreSQL.

## Implantar no Railway
1. Crie **um novo repositório** GitHub com os arquivos desta pasta diretamente na raiz. **Não** reutilize o repositório da horta.
2. No Railway, crie **um novo projeto** e adicione PostgreSQL novo.
3. Adicione o serviço da aplicação conectado ao novo repositório GitHub; Railway usa o Dockerfile da raiz.
4. Configure no serviço da aplicação as variáveis do `.env.example`. Para `DATABASE_URL`, use referência à variável do novo Postgres, por exemplo `${{Postgres.DATABASE_URL}}`, ajustando o nome do serviço se necessário.
5. Use `SECRET_KEY` aleatória forte; `COOKIE_SECURE=1`; e-mails individuais e senhas novas e fortes. Ajuste `APP_TIMEZONE`.
6. Em Networking, gere o domínio HTTPS do novo serviço e aplique o deploy. Verifique `/health`, login, criação, conclusão e persistência após redeploy.
7. Ative backups do PostgreSQL na Railway e monitore consumo.

**Importante:** Os usuários são criados apenas quando o e-mail ainda não existe. Alterar a variável de senha posteriormente **não** troca a senha do usuário existente. Evite usar senhas de exemplo.

## Notificações no celular (opcional)
Configure `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` e `VAPID_SUBJECT` (ex. `mailto:email@dominio.com`). Você pode gerar um par VAPID com a biblioteca `py-vapid` (`vapid --gen` e exportar chaves correspondentes) ou ferramenta equivalente. Guarde a chave privada apenas nas variáveis do Railway. O app oferece botão de ativação em Preferências.

No iPhone/iPad: instale como app na Tela de Início antes de permitir notificações. Em Android: instale/adicone à tela inicial pelo navegador. O usuário deve autorizar a permissão. Os avisos requerem conectividade com o servidor, um dispositivo compatível e envio push habilitado. O worker verifica aproximadamente a cada minuto; mantenha **uma réplica/worker Uvicorn** para evitar concorrência. Alertas já vencidos ou de eventos concluídos não são enviados. Entregas dependem do serviço de push do sistema e **não são garantidas**; não use como único lembrete para compromissos críticos.

## Limites e melhorias futuras
Esta primeira versão não possui sincronização Google Calendar/Apple Calendar, anexos, eventos recorrentes, convite por e-mail, recuperação de senha automatizada, edição de perfil ou visualização mensal. Cada conta pode modificar todos os compromissos da agenda compartilhada. O aplicativo é um PWA (não são aplicativos nativos publicados nas lojas).

Para operação mais robusta, mover notificações para um serviço agendado/worker dedicado com locks transacionais e retentativas, configurar migrações Alembic, monitoramento, políticas de backup, redefinição de senha e testes de carga.
