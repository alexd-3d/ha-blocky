/*
 * More texts of the card (the dashboard toolbar, the legend hints, the groups
 * of the Settings tab), in the same two languages as ha-blocky-i18n.js, which
 * merges them. English first; the Ukrainian table mirrors it key for key.
 */

/* i18n:en */
export const MORE_EN = {
  "card_error": "The card could not start. Reload the page.",
  "dash_pause_for": "Pause for",
  "dash_refresh_lists": "Refresh lists",
  "dash_flush_cache": "Flush cache",
  "dash_tool_error": "The action failed.",
  "dash_minutes": "{n} min",
  "dash_hours": "{n} h",
  "cat_hint_resolved": "Resolved: the query was answered by an upstream DNS server.",
  "cat_hint_cached": "Cached: the answer came from Blocky's own cache.",
  "cat_hint_local": "Local: answered from custom DNS, conditional rules or the hosts file.",
  "cat_hint_blocked": "Blocked: refused because the domain is on a deny list.",
  "cat_hint_other": "Other: any other kind of answer, for example an error or a special rule.",
  "set_group_defaults": "Dashboard defaults",
  "set_group_intervals": "Polling intervals",
  "set_group_general": "Reporting and sidebar",
  "search_ip": "IP address",
  "search_name": "Client name",
  "ignore_type": "Ignore query type: merge rows that differ only by type (A, AAAA, HTTPS)",
  "bad_ip_filter": "The IP filter may hold only digits, the letters a-f, dots and colons (45 characters at most).",
  "bad_name_filter": "That client name filter is not valid.",
  "dash_open_log": "Show this client's queries in the Query log",
  "perr_invalid_name": "The name must be 1 to 64 characters without control characters.",
  "perr_too_many_names": "Too many client names are stored already.",
  "perr_invalid_ip": "That is not a valid IP address.",
  "prot_base_default_warning": "The list groups of the Standard level are still the built-in default (default). If your Blocky uses other names for its list groups, Standard clients lose their lists. Enter your names below and save."
};
/* i18n:end */

/* i18n:uk */
export const MORE_UK = {
  "card_error": "Не вдалося запустити картку. Оновіть сторінку.",
  "dash_pause_for": "Пауза на",
  "dash_refresh_lists": "Оновити списки",
  "dash_flush_cache": "Очистити кеш",
  "dash_tool_error": "Не вдалося виконати дію.",
  "dash_minutes": "{n} хв",
  "dash_hours": "{n} год",
  "cat_hint_resolved": "Від upstream: запит обробив вищий DNS-сервер.",
  "cat_hint_cached": "З кешу: відповідь узято з власного кешу Blocky.",
  "cat_hint_local": "Локально: відповідь із власного DNS, умовних правил або файлу hosts.",
  "cat_hint_blocked": "Заблоковано: відхилено, бо домен є у списку заборони.",
  "cat_hint_other": "Інше: будь-який інший тип відповіді, наприклад помилка чи особливе правило.",
  "set_group_defaults": "Типові значення панелі",
  "set_group_intervals": "Інтервали опитування",
  "set_group_general": "Звіти та бічна панель",
  "search_ip": "IP-адреса",
  "search_name": "Назва клієнта",
  "ignore_type": "Ігнорувати тип запиту: об'єднувати рядки, що відрізняються лише типом (A, AAAA, HTTPS)",
  "bad_ip_filter": "Фільтр IP може містити лише цифри, літери a-f, крапки та двокрапки (не більше 45 символів).",
  "bad_name_filter": "Недійсний фільтр за назвою клієнта.",
  "dash_open_log": "Показати запити цього клієнта в журналі запитів",
  "perr_invalid_name": "Назва має містити від 1 до 64 символів без керівних символів.",
  "perr_too_many_names": "Уже збережено забагато назв клієнтів.",
  "perr_invalid_ip": "Це не коректна IP-адреса.",
  "prot_base_default_warning": "Групи списків рівня «Стандартний» досі мають вбудоване значення (default). Якщо ваш Blocky називає свої групи списків інакше, клієнти зі Стандартним рівнем втратять свої списки. Введіть свої назви нижче та збережіть."
};
/* i18n:end */
