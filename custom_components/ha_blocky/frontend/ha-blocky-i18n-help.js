/*
 * Texts of the Help tab, in the same two languages as ha-blocky-i18n.js (which
 * merges them), and the three blocklist sources the Help tab shows as plain
 * text. The sources are never fetched and never made links.
 */

/* i18n:en */
export const HELP_EN = {
  "help_quick_title": "Quick start",
  "help_tab_dashboard": "Dashboard: the blocking switch, totals, a chart of queries over time and the top clients, domains and blocked domains for a period.",
  "help_tab_log": "Query log: every DNS query with search and filters. Live mode follows new queries. Use the icons to allow or block a domain.",
  "help_tab_requests": "Requests: new domains that Restricted and Lockdown clients asked for, waiting for your decision, and the known domains of each client.",
  "help_tab_settings": "Settings: the level of each client, notifications, rules and the block to paste into Blocky, then colours, default rows, update intervals and the sidebar entry.",
  "help_names_title": "Name a client",
  "help_names_body": "Click a client in the query log, the Requests tab or the overview card, type a name of up to 64 characters and press Enter to save. Escape cancels; an empty name clears it. The name is kept by Home Assistant for that IP address. Without a typed name, the friendly name of a device tracker with that IP address is used, else the address is shown.",
  "help_actions_title": "Allow and block",
  "help_actions_body": "In the query log, an answered row has a Block icon and a blocked row has an Allow icon. Choose one of the four lists (Always allow, Always block, the Restricted block list or the Lockdown allow list) and confirm; Blocky reloads its lists a few seconds later. Requests: a Restricted client's request offers Block (adds the domain to the Restricted block list) or Dismiss. A Lockdown client's request offers Approve (adds the exact domain to the Lockdown allow list) or Reject (it never asks again for that client and domain). Both lists apply to every client of that level.",
  "help_faq_title": "Questions",
  "help_faq_delay_q": "Why do new queries show up late?",
  "help_faq_delay_a": "Blocky writes its query log to the database in batches, by default every 30 seconds. Polling faster does not help.",
  "help_faq_pause_q": "What does the blocking switch do?",
  "help_faq_pause_a": "Turning it off pauses blocking for a limited time; blocking then resumes on its own.",
  "help_faq_name_q": "Why did a client lose its name?",
  "help_faq_name_a": "Names are kept per IP address. If the router gives the device another address, it shows unnamed until you name it again. A reserved address avoids this.",
  "help_faq_nodb_q": "Why does the dashboard show no numbers?",
  "help_faq_nodb_a": "The statistics need the query log database. Set it up in the Configure menu of the integration.",
  "help_faq_sidebar_q": "Where did the sidebar entry go?",
  "help_faq_sidebar_a": "It is switched off in Settings under \"Show in sidebar\". The card still works from a dashboard.",
  "help_lists_title": "Add well-known blocklists",
  "help_lists_body": "Blocklist sources are added as list sources in Blocky's own configuration, in its blocking section (for the Blocky app, in the configuration of the app). HA-Blocky does not download or apply them. The three sources below are plain text you can copy; check the page of a list before you use it.",
  "help_copy": "Copy",
  "help_copied": "Copied",
  "help_copy_failed": "Select the text and copy it by hand."
};
/* i18n:end */

/* i18n:uk */
export const HELP_UK = {
  "help_quick_title": "Швидкий старт",
  "help_tab_dashboard": "Панель: перемикач блокування, підсумки, графік запитів у часі та топ клієнтів, доменів і заблокованих доменів за період.",
  "help_tab_log": "Журнал запитів: усі DNS-запити з пошуком і фільтрами. Режим «Наживо» стежить за новими запитами. Іконками можна дозволити або заблокувати домен.",
  "help_tab_requests": "Запити: нові домени, які запитували клієнти рівнів «Обмежений» і «Лише дозволене», що чекають вашого рішення, і відомі домени кожного клієнта.",
  "help_tab_settings": "Налаштування: рівень кожного клієнта, сповіщення, правила та блок для вставлення в Blocky, далі кольори, кількість рядків, інтервали оновлення та пункт бічної панелі.",
  "help_names_title": "Назвати клієнта",
  "help_names_body": "Натисніть клієнта в журналі запитів, на вкладці «Запити» або в картці огляду, введіть назву до 64 символів і натисніть Enter, щоб зберегти. Escape скасовує; порожня назва очищає. Назву зберігає Home Assistant для цієї IP-адреси. Без введеної назви береться ім'я пристрою-трекера з такою IP-адресою, інакше показується адреса.",
  "help_actions_title": "Дозволити і заблокувати",
  "help_actions_body": "У журналі запитів рядок із відповіддю має іконку «Заблокувати», а заблокований - «Дозволити». Виберіть один із чотирьох списків («Завжди дозволяти», «Завжди блокувати», список блокування рівня «Обмежений» або список дозволених рівня «Лише дозволене») і підтвердіть; Blocky перечитає списки за кілька секунд. Запити: запит клієнта рівня «Обмежений» пропонує «Заблокувати» (додає домен до списку блокування цього рівня) або «Закрити». Запит клієнта рівня «Лише дозволене» пропонує «Схвалити» (додає точний домен до списку дозволених цього рівня) або «Відхилити» (для цього клієнта й домену більше не питатиме). Обидва списки діють для кожного клієнта свого рівня.",
  "help_faq_title": "Запитання",
  "help_faq_delay_q": "Чому нові запити з'являються із запізненням?",
  "help_faq_delay_a": "Blocky записує журнал запитів у базу пакетами, типово кожні 30 секунд. Частіше опитувати немає сенсу.",
  "help_faq_pause_q": "Що робить перемикач блокування?",
  "help_faq_pause_a": "Вимкнення призупиняє блокування на обмежений час; потім блокування відновлюється саме.",
  "help_faq_name_q": "Чому клієнт втратив назву?",
  "help_faq_name_a": "Назви зберігаються за IP-адресою. Якщо маршрутизатор видасть пристрою іншу адресу, він з'явиться без назви, доки ви не назвете його знову. Зарезервована адреса цього уникає.",
  "help_faq_nodb_q": "Чому на панелі немає чисел?",
  "help_faq_nodb_a": "Статистика потребує бази даних журналу запитів. Налаштуйте її в меню «Налаштувати» інтеграції.",
  "help_faq_sidebar_q": "Куди зник пункт бічної панелі?",
  "help_faq_sidebar_a": "Його вимкнено в Налаштуваннях у пункті «Показувати в бічній панелі». Картка й далі працює на панелі керування.",
  "help_lists_title": "Додати відомі списки блокування",
  "help_lists_body": "Джерела списків блокування додаються як джерела списків у власній конфігурації Blocky, у її розділі blocking (для додатка Blocky - у конфігурації додатка). HA-Blocky їх не завантажує і не застосовує. Три джерела нижче - звичайний текст, який можна скопіювати; перед використанням перегляньте сторінку списку.",
  "help_copy": "Копіювати",
  "help_copied": "Скопійовано",
  "help_copy_failed": "Виділіть текст і скопіюйте вручну."
};
/* i18n:end */

// Well-known blocklists: a name and the address to copy into Blocky's
// configuration. These three are the only ones.
export const BLOCKLISTS = [
  {
    name: "StevenBlack hosts",
    url: "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
  },
  {
    name: "HaGeZi Pro (wildcard format)",
    url: "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/pro.txt",
  },
  {
    name: "OISD big (wildcard format)",
    url: "https://big.oisd.nl/domainswild",
  },
];
