# Скрипт для обработки дублей
# Создаёт линки на тикеты, которые указаны в комментариях(OPS-12345) и закрыты с resolution = Duplicate

from jira import JIRA
import oauthlib.oauth1
import re

JIRA_SERVER = "https://jira.osmp.ru"
# # Подключение к Jira через OAuth #
# RSA_KEY = '/ru-svc-vmw-scripts.pem'
#
# key_cert_data = None
# with open(RSA_KEY, 'r') as key_cert_file:
#     key_cert_data = key_cert_file.read()

# oauth_token = 'pub_token'
# oauth_token_secret = 'priv_token'              # WARNING:jira:Warning: Specified issue link type is not present in the list of link types из за oauth=oauth_dict
# oauth_dict = {
#     'access_token': oauth_token,
#     'access_token_secret': oauth_token_secret,
#     'consumer_key': 'ru-svc-vmw-scripts',
#     'key_cert': key_cert_data,
#     'signature_method': oauthlib.oauth1.SIGNATURE_RSA_SHA1
# }
# jira = JIRA(server=JIRA_SERVER, oauth=oauth_dict)

jira = JIRA(server=JIRA_SERVER, basic_auth=('username', 'password'))

# Создаем JQL запрос (https://jira.osmp.ru/issues/?filter=78402)
JQL = "project = OPS AND resolution = Duplicate AND comment ~ '*OPS-*' AND status changed to CLOSED during (-24h, now())  ORDER BY updated DESC"

# Ищем тикеты по нашему запросу JQL
issues = jira.search_issues(JQL)


def issue_link(issue, main_issue):
    inwardIssue = jira.issue(issue)
    outwardIssue = jira.issue(main_issue)
    issueLinkType = 'relates'
    jira.create_issue_link(issueLinkType, inwardIssue, outwardIssue)


for issue in issues:
    # Ищем главный тикет из последнего комментария к которому линковать дубли
    comments = jira.comments(issue)
    last_comment = comments[-1].body
    main_issue = re.findall(r'SS-\d{5}', last_comment)
    main_issue = ''.join(main_issue)

    try:
        issue_link(issue, main_issue)
    except jira.exceptions.JIRAError as er:
        print(f'Error{main_issue}: {er}')
