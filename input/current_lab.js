/*
 * PizzaMan Dan - Lean Grok-controlled ordering-through-card-and-submit lab
 * Exact-tool-contract evaluation lab - current menu/compiler schemas + raw customer-safe tool results + private card token and submit
 *
 * Standalone Voximplant scenario. Load ONLY this file for the lab.
 * Do not load PizzaGuardGrokV2.js, PizzaRuntimeGrokV2.js, or PizzaTransportGrokV2.js.
 *
 * Required Voximplant Secrets:
 *   GROK_API_KEY
 *   PMD_BACKEND_API_KEY
 */

require(Modules.Grok);

var LAB_VARIANT = "LEAN_RUNTIME_LIVE_MENU_PARITY_NO_SILENT_DROPS";
var LAB_BOOT = "PMD_TF1_LIVE_MENU_PARITY_NO_SILENT_DROPS_2026_08_04";
var LAB_MODEL = "grok-voice-think-fast-1.0";
var LAB_REASONING_EFFORT = "high";
var LAB_STORE_NUMBER = 1;
var LAB_ORDER_TYPE = "P";
var LAB_EMPLOYEE_NUMBER = "9090";
var LAB_BASE_URL = "https://pizza-ai-backend.onrender.com";
var LAB_CALL_LOG_URL = "https://pizzaman-call-backend.onrender.com/api/calls/event";
var LAB_CALL_LOG_BATCH_URL = "https://pizzaman-call-backend.onrender.com/api/calls/batch";
var LAB_CALL_LOG_FLUSH_DURING_CALL = false;
var LAB_TRANSFER_SIP_DESTINATION_SECRET = "TRANSFER_SIP_DESTINATION";
var LAB_TRANSFER_SIP_DOMAIN_SECRET = "TRANSFER_SIP_DOMAIN";
var LAB_TRANSFER_DEFAULT_SIP_DOMAIN = "sbc.simplelogin.net";
var LAB_SILENCE_REPROMPT_MS = 6000;
var LAB_RESPONSE_TIMEOUT_MS = 15000;
var LAB_PICKUP_STORE_NAME = "Mock Store";
var LAB_PICKUP_ADDRESS = "450 S Victoria Ave, Oxnard";
var LAB_PICKUP_LANDMARK = "at the corner of 5th and Victoria";
var LAB_PICKUP_LOCATION_FOR_READBACK = LAB_PICKUP_STORE_NAME + ", " + LAB_PICKUP_ADDRESS + ", " + LAB_PICKUP_LANDMARK;

var LAB_PROMPT = [
  "You are taking a PizzaMan Dan pickup order.",
  "",
  "OWNERSHIP",
  "- You own the complete current customer-facing order, the pending item sequence, the active item, corrections, confirmations, compile, final approval, payment choice, and submit tool calls.",
  "- Runtime only executes tools, forwards results, logs events, retains the latest successful private order_json, handles audio, silence, transfer mechanics, secure keypad capture, and deterministic submission locking.",
  "- You alone interpret natural-language answers, confirmations, corrections, reversals, finished-order answers, and payment choices. Runtime does not use phrase lists to override your meaning decision.",
  "- Tools and tool results are authoritative. Use exact returned customer-facing names. Never invent menu items, options, coupon choices, or recipes.",
  "",
  "ORDER SEQUENCE",
  "- Keep every requested item and coupon in the caller's spoken order.",
  "- Work on exactly one active item or coupon at a time.",
  "- Call only one ordering tool in a response. Never request a second category, coupon, or pending item in that response.",
  "- Ask only the next missing required choice. Ask one customer question, then stop and wait.",
  "- Do not move to the next item until the active item is complete, read back, and confirmed.",
  "- When the active item is complete, read the complete item and ask exactly: Is that right?",
  "- Stop and wait. A yes confirms only that item.",
  "- After confirmation, immediately begin the next pending item. Do not ask Anything else while a pending item remains.",
  "- Only after every pending item and coupon is confirmed, call ask_anything_else silently with no spoken audio and no other tool.",
  "- Runtime will force exactly: Anything else for the order? while this same normal session and all normal tools remain active. Do not speak that question yourself.",
  "- You decide what the caller means. A finish answer leads to compile; an addition or correction stays in ordering; an unclear answer gets one short clarification. Runtime never classifies the answer.",
  "- After the caller answers that question, continue normal ordering or compile. Compile only after you determine the caller is finished.",
  "- The caller's newest correction, removal, cancellation, or replacement overrides only the targeted detail. Preserve every unrelated confirmed item.",
  "- If a plural food item is spoken without a clear quantity, ask how many. Do not assume one.",
  "",
  "TOOL ANNOUNCEMENTS",
  "- Announce each lookup briefly and include the matching tool call in the same response.",
  "- Pizza: say exactly: Let me check the pizza menu.",
  "- Calzone: say exactly: Let me check calzone options.",
  "- Pizza Burger: say exactly: Let me check pizza burger options.",
  "- Actual sub: say exactly: Let me check the sub menu.",
  "- Other food categories: say exactly: Let me check the [category] menu.",
  "- Coupon or numbered special: say exactly: Let me check that coupon.",
  "- Say a lookup announcement only in a response that also contains its matching tool call. Never announce a lookup without calling that tool in the same response.",
  "- Do not repeat a lookup announcement after that result is already available.",
  "- Never use a generic sentence such as I'll get that started, I'll add that, or I'll handle those items.",
  "",
  "MENU",
  "- Use get_ordering_catalog for one category at a time.",
  "- A normal first lookup uses category only.",
  "- When the caller names a specialty pizza, category pizza may include item_query so the current specialty list can return the exact match.",
  "- Pizza Burger is a subs-category item. Its first lookup is category subs without item_query. Never route Pizza Burger to category pizza.",
  "- For subs, item_query is only an options fallback after the full subs result lacks the needed options.",
  "- If the caller requests a sub modification that is not present in the full-category result, call the returned item_query fallback before accepting or confirming that modification. Use only an exact returned option name.",
  "- For beverages, use category beverages without item_query.",
  "- Follow ordering_contract, required_choices, lookup_contract, and next_step returned by the backend for the active item or coupon.",
  "- Returned required choices are authoritative. Ask only the next missing required choice and use the exact returned customer-facing value.",
  "- When a returned field is fixed or says ask=false, skip that question and do not explain the fixed field to the caller.",
  "- Returned optional modifications are not questions. Use them only when the caller asks for a change or asks what is included.",
  "- When a returned contract allows an item_query fallback, use it only after the full category result lacks the needed options for the selected exact item.",
  "- Collect every required size, crust, sauce, dressing, dip, pack, option, or instruction shown by the result before item confirmation.",
  "- Do not ask optional modifications the caller did not request.",
  "- Meatsa, Meatza, Miso, Mesa, or repeated pizza-pizza may mean the current specialty The Meatsa Pizza. Verify against the current specialty list. Never infer its recipe unless included_toppings is returned.",
  "- Universal pizza rule: cheese pizza, plain cheese, or just cheese means the exact current Ultimate 4-Cheese item.",
  "- Universal pizza rule: a pizza named only by one or more toppings means the exact current Build Your Own Pizza with only those named toppings in whole_toppings. Default cheese and red sauce stay implicit unless changed.",
  "- If the caller asks for a one-topping pizza without naming the topping, ask which topping. An exact specialty name remains that specialty and is never converted to Build Your Own.",
  "",
  "COUPONS",
  "- Use get_coupon_plan before describing or building a numbered coupon or known spoken special.",
  "- Treat consecutive spoken coupon digits as one complete coupon number. The newest completed caller wording wins; for example, 3 6 9 means coupon 369.",
  "- Speak every coupon number as separate digits using coupon_spoken_label or coupon_number_for_speech. Say coupon 3 7 1, never coupon three hundred seventy-one.",
  "- Treat one coupon as one active pending item. Use choices the caller already supplied and ask only the next missing coupon choice.",
  "- Do not read the full coupon choice list unless the caller asks what is available.",
  "- Do not repeat already selected coupon items before each next question, and do not narrate what you will do next.",
  "- Follow dependent_required_choices returned by the coupon plan. When a selected coupon item requires dressing or another option, ask it before coupon confirmation and attach the exact answer to that same coupon_component option_names.",
  "- Confirm the completed coupon and its selected components once with Is that right? before moving on.",
  "- Top-level coupon_numbers is the source of coupon lines and repeat quantity. coupon_component.coupon_number only marks component ownership.",
  "- Multiple supported package coupons may be combined. Repeat a normal coupon number for multiple instances when its plan permits it.",
  "- Coupon 999 appears once in top-level coupon_numbers.",
  "- Every coupon 999 pizza is one separate coupon_component row with coupon_number 999, choice_type pizza_choice, and quantity 1.",
  "- Never send a coupon 999 pizza as category pizza and never combine two coupon 999 pizzas into quantity 2.",
  "- For coupon 999, cheese pizza, plain cheese, or just cheese means item_name Ultimate 4-Cheese.",
  "- Preserve ordinary pizzas. Never convert them into coupon 999 pizzas unless the caller explicitly ordered them as part of coupon 999.",
  "- If a coupon plan is unavailable or voice-disabled, do not compile it.",
  "",
  "COMPILE AND READBACK",
  "- Send the complete current cart every time. The compiler is stateless.",
  "- When the caller is finished, start your response with exactly: Compiling and pricing that now.",
  "- In that same response, call compile_and_price_order with the complete current customer-facing cart. Do not wait for another response and do not ask another question.",
  "- Extra speech after the required opening phrase is undesirable but must never prevent the compiler call.",
  "- If compile feedback says retry_without_asking_customer, repair the structure and resend the complete cart without asking again.",
  "- Otherwise ask only first_missing_question and wait. After the caller answers, start the retry response with exactly: Compiling and pricing that now. Then call compile_and_price_order in that same response with the complete preserved cart. Do not say I have noted it or narrate the retry.",
  "- After pricing, begin immediately with the first current food item. Do not repeat Compiling and pricing that now.",
  "- Read every current food item and confirmed identifying option, every coupon and selected component, the pickup store name, address, and landmark, then only the grand total.",
  "- Do not state individual item, coupon, package, unit, subtotal, tax, or line-item prices unless the caller specifically asks.",
  "- End the final readback exactly with: Is everything correct? Then stop and wait.",
  "- You decide whether the answer approves the order or changes it. Natural confirmations such as you got it, go ahead, or that works may approve. A confirmation plus an exception is a correction, not approval.",
  "- Any correction after pricing requires the complete corrected cart to be compiled and priced again before submission.",
  "- Do not say the customer name, California, C A, internal IDs, field names, JSON, or tool names.",
  "",
  "PAYMENT AND SUBMIT",
  "- After the caller approves the final readback, ask exactly: Would you like to pay by card with me now, or pay at the store when you arrive?",
  "- Stop and wait. You decide the caller's natural-language payment choice. The newest completed correction wins; for example, card—no, store means pay at store.",
  "- If the caller chooses pay at the store, say exactly: Submitting that now. Then call submit_order in the same response with payment_method pay_at_store.",
  "- If the caller chooses card, say exactly: Please enter the card number on your keypad. When you're done, say okay.",
  "- Secure keypad capture proceeds card number, expiration as MMYY, then billing ZIP. Never ask for CVV and never repeat keypad digits.",
  "- The caller may still switch payment method before a successful submission. Interpret the newest choice yourself. To switch to pay at store, call submit_order with payment_method pay_at_store; Runtime will clear private card data.",
  "- After the billing ZIP is complete, say exactly: Processing. Then call get_payment_token.",
  "- After get_payment_token succeeds, say exactly: Submitting that now. Then call submit_order with payment_method card.",
  "- Runtime permits only one submission attempt at a time. A confirmed successful order becomes permanently locked. A confirmed failure may be retried. An unknown submission result may not be retried and must be transferred to staff.",
  "- After submit succeeds, say only the customer-facing order number and pickup estimate. Do not say to bring an order number or identification, do not repeat the store or order, and do not add an offer of further help or a farewell.",
  "- Once an order is successfully submitted, you cannot modify it, add or remove items, cancel it, add or change payment, take another payment, or resubmit it. Any such request must be transferred to live staff.",
  "",
  "TRANSFER",
  "- If the caller explicitly asks for a person, staff member, or transfer, say exactly: I'll transfer you to a member of our team. Please stay on the line. Then call transfer_call in the same response.",
  "- If you are confused, stuck, or think staff may be better, ask exactly: Would you like me to transfer you to a member of our team? Then stop and wait.",
  "- A complaint such as I think you are lost is not transfer permission. Call transfer_call only after an explicit transfer request or a clear yes to the transfer offer.",
  "- Only an actual WebSocket or runtime failure may transfer without asking; Runtime handles that fallback.",
  "",
  "SPEECH",
  "- Keep speech short, natural, and useful.",
  "- Stop speaking immediately after the one customer question.",
  "- Do not narrate reasoning, plans, schemas, or internal processing.",
  "",
  "This lab uses Mock Store 1."
].join("\n");

var LAB_ITEM_SCHEMA = {
  type: "object",
  properties: {
    category: {
      type: "string",
      description: "Food category for a real item: pizza, calzone, wings, salads, beverages, subs, sides_appetizers, or desserts. Use coupon_component only for an included coupon choice."
    },
    text: {
      type: "string",
      description: "Optional current customer-facing item readback. If present, it must agree with every structured field and must not contain removed or replaced wording."
    },
    quantity: {
      type: "integer",
      minimum: 1,
      description: "Quantity of this exact configured item. For coupon 999 pizza_choice components, quantity must be exactly 1 because each pizza is its own line."
    },
    item_name: {
      type: "string",
      description: "Exact customer-facing item name returned by get_ordering_catalog, or by get_coupon_plan for a coupon_component."
    },
    choice_type: {
      type: "string",
      description: "For coupon_component only: exact coupon-plan choice type, such as main, pizza_choice, calzone, half_sub, drink, salad, salad_dressing, wing_sauce, pizza_topping, appetizer, or menu. Coupon 999 pizzas use pizza_choice."
    },
    coupon_number: {
      type: "integer",
      description: "For coupon_component only: customer-facing coupon number owning this component. Every coupon 999 pizza row uses coupon_number 999."
    },
    option_names: {
      type: "array",
      items: {type: "string"},
      description: "Exact customer-facing options returned for this exact item, such as a sub option, wing sauce, All Drums/No Drums instruction when returned as an option, salad dressing, or calzone dip."
    },
    size: {
      type: "string",
      description: "One exact item size, such as Medium, Small, Half Sub, CAN, 6 Pack, or 2 Liter. Use the singular size field."
    },
    crust: {
      type: "string",
      description: "One exact pizza crust/style from crusts_by_size, such as Thin Crust, Pan Style, or Gluten Free. Gluten Free is a crust, not a second size."
    },
    sauce: {
      type: "string",
      description: "Exact pizza sauce only when requested or required by the returned menu."
    },
    whole_toppings: {
      type: "array",
      items: {type: "string"},
      description: "Positive whole-pizza toppings for a Build Your Own pizza. For a specialty pizza, leave kept defaults implicit and use add_toppings/remove_toppings only for actual changes."
    },
    add_toppings: {
      type: "array",
      items: {type: "string"},
      description: "Exact toppings the caller explicitly adds to the pizza, especially additions to a specialty pizza."
    },
    remove_toppings: {
      type: "array",
      items: {type: "string"},
      description: "Exact toppings the caller removes: no, without, hold, remove, take off, or subtract. Never put a removed topping in whole_toppings or add_toppings."
    },
    first_half_toppings: {
      type: "array",
      items: {type: "string"},
      description: "Exact toppings on the first/left/one half only."
    },
    second_half_toppings: {
      type: "array",
      items: {type: "string"},
      description: "Exact toppings on the second/right/other half only."
    },
    instructions: {
      type: "array",
      items: {type: "string"},
      description: "Exact customer-facing instruction names returned by the menu, such as Square Cut, All Drums, or No Drums."
    }
  },
  required: ["category", "item_name"],
  additionalProperties: true
};

var LAB_TOOLS = [
  {
    type: "function",
    name: "get_ordering_catalog",
    description: "Call only for the one active item. Before calling, speak the matching approved lookup announcement in the same response. Return the current customer-facing food menu for one category. This tool never exposes oneSystem IDs. Use a full category lookup for normal ordering. When the caller names a specialty pizza, category=pizza may include item_query; the result will expose matched_item and detected_specialty from the current specialty_pizzas list. Pizza Burger always uses category=subs: first call the full subs category without item_query, then use item_query only if the returned contract requires an options fallback. For other subs, item_query is an options fallback after the full subs menu is missing required options for that exact sub. For calzones use category=calzone. For beverages use category=beverages without item_query. Do not invent items or choices outside the returned menu.",
    parameters: {
      type: "object",
      properties: {
        store_number: {type: "integer", description: "Store number. This lab always uses 1."},
        order_type: {type: "string", enum: ["P", "D", "pickup", "delivery"], description: "Pickup or delivery. This lab always uses pickup/P."},
        category: {
          type: "string",
          enum: ["pizza", "calzone", "wings", "subs", "salads", "sides_appetizers", "desserts", "beverages"],
          description: "One full menu category."
        },
        item_query: {
          type: "string",
          description: "Optional exact or close caller wording. Use with category=pizza when the caller names a specialty pizza so the tool can return the exact current matched_item/detected_specialty. Use with category=subs only as an item-options fallback. Do not use for calzone, wings, salads, sides, desserts, or beverages."
        }
      },
      required: ["store_number", "order_type", "category"],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "get_coupon_plan",
    description: "Call only when a coupon or special is the one active pending item. Before calling, say exactly: Let me check that coupon. Use coupon_number when the caller gives a number. Consecutive spoken digits are one complete coupon number; 3 6 9 means 369. Use query when the caller gives a special name or asks which specials or lunch specials are available. The backend returns customer-safe current plans, required choices, dependent_required_choices, availability, and an exact compile contract. Ask each dependent choice before confirming the coupon and attach it to the same selected coupon_component. Do not require the caller to know a coupon number and do not invent coupon contents.",
    parameters: {
      type: "object",
      properties: {
        store_number: {type: "integer", description: "Store number. This lab always uses 1."},
        order_type: {type: "string", enum: ["P", "D", "pickup", "delivery"], description: "Pickup or delivery. This lab always uses pickup/P."},
        coupon_number: {type: "integer", description: "Customer-facing coupon or special number when the caller gives one."},
        query: {type: "string", description: "Customer wording for a named special or a request to list current specials, such as Manager's Special or lunch specials."}
      },
      required: ["store_number", "order_type"],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "compile_and_price_order",
    description: "Call only after every pending item and coupon was individually confirmed and the caller explicitly finished ordering. Start the same response with exactly: Compiling and pricing that now. Then call this tool in that same response with the complete current customer-facing order. Do not wait for a second response. Compile and immediately price the complete current customer-facing order. The compiler is stateless: send the whole current cart every time. Runtime supplies store_number, order_type, phone, customer_name, delivery, and curbside from current session information. Structured cart fields are the source of truth. Copy exact customer-facing names from get_ordering_catalog and get_coupon_plan. Do not send oneSystem IDs. For specialty pizzas, keep default toppings implicit and use add_toppings/remove_toppings for actual changes. For Build Your Own pizzas, use whole_toppings. Put Square Cut, All Drums, and No Drums in instructions when returned as instruction names. Put a beverage choice in singular size. Coupons require top-level coupon_numbers plus selected coupon_component rows. Coupon 999 appears once at top level, and every qualifying pizza is one separate coupon_component row with coupon_number 999, choice_type pizza_choice, and quantity 1. Cheese/plain cheese means item_name Ultimate 4-Cheese. Never send coupon 999 pizzas as ordinary category pizza rows. If the result returns retry_without_asking_customer, correct the structure and resend without asking the caller. Otherwise, if it returns first_missing_question or missing_questions, ask only the first question and wait. After the caller answers, start with Compiling and pricing that now and call this tool again in the same response with the complete preserved cart.",
    parameters: {
      type: "object",
      properties: {
        coupon_number: {type: "integer", description: "Customer-facing coupon number for one coupon line. Prefer coupon_numbers for package coupons and repeats."},
        coupon_numbers: {type: "array", items: {type: "integer"}, description: "Customer-facing package coupon lines and quantities. Repeat numbers for multiple specials; coupon 999 appears only once."},
        items: {
          type: "array",
          minItems: 1,
          description: "The complete current customer-facing order, rebuilt from what the caller wants now. Runtime supplies all session and customer fields.",
          items: LAB_ITEM_SCHEMA
        }
      },
      required: ["items"],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "ask_anything_else",
    description: "Call silently only after every pending item and coupon is complete and individually confirmed. Produce no spoken audio and call no other tool in this response. Runtime will force exactly: Anything else for the order? without replacing this normal session or removing tools. You interpret the caller answer and continue ordering, correct the cart, clarify, or compile.",
    parameters: {
      type: "object",
      properties: {},
      required: [],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "get_payment_token",
    description: "Tokenize the runtime-captured keypad card after the final priced order is approved. Call with store_number only. Runtime privately supplies card number, expiration, billing ZIP, phone, name, and street. Never pass or speak raw card fields and never ask for CVV.",
    parameters: {
      type: "object",
      properties: {
        store_number: {type: "integer", description: "Store number. This lab always uses 1."}
      },
      required: [],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "submit_order",
    description: "Call only after the caller approves the current final readback and chooses a payment method. Immediately before calling, say exactly: Submitting that now. Pass payment_method as card or pay_at_store so your language decision is explicit. Card requires a saved successful token. Runtime atomically blocks duplicate in-flight or successful submissions. Do not rebuild or include the cart.",
    parameters: {
      type: "object",
      properties: {payment_method: {type: "string", enum: ["card", "pay_at_store"], description: "The payment method the caller most recently chose."}},
      required: ["payment_method"],
      additionalProperties: false
    }
  },
  {
    type: "function",
    name: "transfer_call",
    description: "Transfer the live caller to staff by SIP REFER only after the caller explicitly requests a person/transfer or clearly says yes to the exact transfer offer. If the agent is merely confused or stuck, ask exactly: Would you like me to transfer you to a member of our team? and wait. Before an approved transfer, say exactly: I'll transfer you to a member of our team. Please stay on the line. Call with a short reason. Do not keep talking after a successful transfer request.",
    parameters: {
      type: "object",
      properties: {
        reason: {type: "string", description: "Short customer-facing reason for transfer."}
      },
      required: [],
      additionalProperties: false
    }
  }
];

function L(value) {
  Logger.write(String(value));
}

function logChunks(label, value) {
  var text = typeof value === "string" ? value : JSON.stringify(value);
  var size = 2800;
  var count = Math.max(1, Math.ceil(text.length / size));
  for (var i = 0; i < count; i++) {
    L(label + "_CHUNK " + (i + 1) + "/" + count + " " + text.slice(i * size, (i + 1) * size));
  }
}

function parseArgs(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try { return JSON.parse(String(raw)); }
  catch (e) {
    L("LAB_TOOL_ARGS_PARSE_ERROR " + e + " raw=" + String(raw));
    return {};
  }
}

function safeClone(value) {
  try { return JSON.parse(JSON.stringify(value)); }
  catch (_) { return value; }
}

function normalizePhone(value) {
  var digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 11 && digits.charAt(0) === "1") digits = digits.slice(1);
  if (digits.length !== 10) return "805-555-0100";
  return digits.slice(0, 3) + "-" + digits.slice(3, 6) + "-" + digits.slice(6);
}


function normalizeMenuMatchText(value) {
  var text = String(value || "").toLowerCase();
  text = text.replace(/meatza/g, "meatsa");
  text = text.replace(/[^a-z0-9]+/g, " ").replace(/^\s+|\s+$/g, "");
  var words = text ? text.split(/\s+/) : [];
  var kept = [];
  for (var i = 0; i < words.length; i++) {
    if (words[i] === "the" || words[i] === "pizza" || words[i] === "specialty") continue;
    kept.push(words[i]);
  }
  return kept.join(" ");
}

function findCurrentSpecialtyMatch(menuResult, itemQuery) {
  var query = normalizeMenuMatchText(itemQuery);
  if (!query || !menuResult || !Array.isArray(menuResult.specialty_pizzas)) return null;

  var best = null;
  var bestScore = 0;
  var queryTokens = query.split(/\s+/);

  for (var i = 0; i < menuResult.specialty_pizzas.length; i++) {
    var candidate = menuResult.specialty_pizzas[i] || {};
    var name = String(candidate.name || "");
    var normalized = normalizeMenuMatchText(name);
    if (!normalized) continue;

    if (normalized === query) return candidate;

    var score = 0;
    if (normalized.indexOf(query) >= 0 || query.indexOf(normalized) >= 0) score = 100;
    else {
      var candidateTokens = normalized.split(/\s+/);
      var overlap = 0;
      for (var q = 0; q < queryTokens.length; q++) {
        if (candidateTokens.indexOf(queryTokens[q]) >= 0) overlap += 1;
      }
      score = overlap * 10;
      if (overlap === queryTokens.length) score += 20;
    }

    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }

  return bestScore >= 20 ? best : null;
}

function enrichPizzaSpecialtyLookup(menuResult, itemQuery) {
  if (!menuResult || String(menuResult.category || "") !== "pizza") return menuResult;
  var query = String(itemQuery || "").replace(/^\s+|\s+$/g, "");
  if (!query) return menuResult;

  var match = findCurrentSpecialtyMatch(menuResult, query);
  menuResult.item_query = query;

  if (menuResult.query_ignored !== undefined) {
    menuResult.backend_query_ignored = menuResult.query_ignored;
    delete menuResult.query_ignored;
  }

  if (match && match.name) {
    menuResult.matched_item = String(match.name);
    menuResult.detected_specialty = String(match.name);
    menuResult.specialty_match = {
      name: String(match.name),
      category: "specialty_pizza",
      source: "current specialty_pizzas"
    };
    if (Array.isArray(match.included_toppings)) {
      menuResult.included_toppings = safeClone(match.included_toppings);
      menuResult.specialty_match.included_toppings = safeClone(match.included_toppings);
    }
    if (Array.isArray(match.free_upon_request)) {
      menuResult.free_upon_request = safeClone(match.free_upon_request);
      menuResult.specialty_match.free_upon_request = safeClone(match.free_upon_request);
    }
    menuResult.query_policy = "item_query was resolved against the current specialty_pizzas returned by this catalog. Use matched_item/detected_specialty exactly. Describe the recipe only when included_toppings is present.";
    L("LAB_SPECIALTY_MATCH query=" + query + " matched=" + String(match.name));
  } else {
    menuResult.specialty_match = null;
    menuResult.item_query_not_matched = true;
    menuResult.query_policy = "No current specialty pizza matched item_query. Ask the caller to clarify using the returned specialty_pizzas names.";
    L("LAB_SPECIALTY_MATCH_NONE query=" + query);
  }

  return menuResult;
}



function normalizePickupEstimateForSpeech(value) {
  var text = String(value || "").trim();
  text = text.replace(/\bmins?\b/gi, "minutes");
  return text;
}

function buildPostSubmitInstructions(orderNumber, pickupEstimate) {
  var number = String(orderNumber || "").trim();
  var estimate = normalizePickupEstimateForSpeech(pickupEstimate);
  var spoken = number ? ("Your order number is " + number + ".") : "Your order has been submitted.";
  if (estimate) spoken += " It should be ready in about " + estimate + ".";
  return 'Say exactly: "' + spoken + '" Say nothing else. Do not say to bring the order number or identification. Do not repeat the store, address, landmark, order, total, or payment method. Do not offer further help and do not add a farewell. Call no tool.';
}

function stripCaliforniaForSpeech(value) {
  var text = String(value || "");
  text = text.replace(/,\s*CA(?=\s|,|$)/gi, "");
  text = text.replace(/,\s*California(?=\s|,|$)/gi, "");
  text = text.replace(/\s{2,}/g, " ").replace(/,\s*,/g, ",").replace(/^\s+|\s+$/g, "");
  return text;
}

function stripPricesForSpeech(value) {
  var text = String(value || "");
  text = text.replace(/\$\s*\d+(?:\.\d{1,2})?\s*(?:each|ea\.?|per\s+item)?/gi, "");
  text = text.replace(/\b\d+\.\d{2}\s+each\b/gi, "");
  text = text.replace(/\s{2,}/g, " ").replace(/\s+([,.;:])/g, "$1").replace(/^\s+|\s+$/g, "");
  return text;
}

function stripPricesFromCustomerFacingStrings(value) {
  if (Array.isArray(value)) {
    var arrayCopy = [];
    for (var i = 0; i < value.length; i++) arrayCopy.push(stripPricesFromCustomerFacingStrings(value[i]));
    return arrayCopy;
  }
  if (!value || typeof value !== "object") {
    return typeof value === "string" ? stripPricesForSpeech(value) : value;
  }
  var copy = {};
  for (var key in value) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
    copy[key] = stripPricesFromCustomerFacingStrings(value[key]);
  }
  return copy;
}


function couponNumberDigitsForSpeech(value) {
  var digits = String(value === undefined || value === null ? "" : value).replace(/\D/g, "");
  return digits ? digits.split("").join(" ") : "";
}

function digitTokenToCharacter(token) {
  var normalized = String(token || "").toLowerCase();
  var words = {
    zero: "0", oh: "0", o: "0",
    one: "1", two: "2", three: "3", four: "4", five: "5",
    six: "6", seven: "7", eight: "8", nine: "9"
  };
  if (/^\d$/.test(normalized)) return normalized;
  return Object.prototype.hasOwnProperty.call(words, normalized) ? words[normalized] : "";
}

function findCouponNumberCandidate(text, preferFirst) {
  var source = String(text || "").toLowerCase();
  var tokenPattern = "(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|\\d)";
  var separatedPattern = new RegExp("\\b" + tokenPattern + "(?:[\\s,.;:\\-]+" + tokenPattern + "){1,5}\\b", "gi");
  var singleTokenPattern = new RegExp(tokenPattern, "gi");
  var candidates = [];
  var match;
  while ((match = separatedPattern.exec(source)) !== null) {
    var pieces = match[0].match(singleTokenPattern) || [];
    var digits = "";
    for (var i = 0; i < pieces.length; i++) digits += digitTokenToCharacter(pieces[i]);
    if (digits.length >= 2 && digits.length <= 6) {
      candidates.push({number: Number(digits), digits: digits, index: match.index});
    }
    if (match[0] === "") separatedPattern.lastIndex += 1;
  }
  var contiguousPattern = /\b\d{2,6}\b/g;
  while ((match = contiguousPattern.exec(source)) !== null) {
    candidates.push({number: Number(match[0]), digits: match[0], index: match.index});
  }
  if (!candidates.length) return null;
  candidates.sort(function (a, b) {
    if (a.index !== b.index) return a.index - b.index;
    return b.digits.length - a.digits.length;
  });
  return preferFirst ? candidates[0] : candidates[candidates.length - 1];
}

function completedCouponNumberFromTranscript(transcript) {
  var text = String(transcript || "").trim();
  if (!text) return null;
  var lower = text.toLowerCase();
  var correctionPresent = /\b(?:no|actually|sorry|correction)\b|\bi\s+mean\b/i.test(text);
  if (correctionPresent) return findCouponNumberCandidate(text, false);
  var couponIndex = lower.lastIndexOf("coupon");
  if (couponIndex >= 0) {
    var couponSegment = text.slice(couponIndex + 6, couponIndex + 56);
    var afterCoupon = findCouponNumberCandidate(couponSegment, true);
    if (afterCoupon) return afterCoupon;
  }
  return findCouponNumberCandidate(text, false);
}

function addCouponSpeechFields(output) {
  if (!output || typeof output !== "object") return output;
  var topNumber = output.coupon_number;
  if (topNumber !== undefined && topNumber !== null && String(topNumber).trim() !== "") {
    var topSpeech = couponNumberDigitsForSpeech(topNumber);
    if (topSpeech) {
      output.coupon_number_for_speech = topSpeech;
      output.coupon_spoken_label = "Coupon " + topSpeech;
    }
  }
  var plans = Array.isArray(output.coupon_plans) ? output.coupon_plans : [];
  for (var i = 0; i < plans.length; i++) {
    var plan = plans[i] || {};
    var planSpeech = couponNumberDigitsForSpeech(plan.coupon_number);
    if (!planSpeech) continue;
    plan.coupon_number_for_speech = planSpeech;
    plan.coupon_spoken_label = "Coupon " + planSpeech;
  }
  output.coupon_number_speech_rule = "Speak coupon numbers as separate digits using coupon_spoken_label. Never read a coupon number as a whole number.";
  return output;
}

function firstCustomerFacingName(value) {
  if (!value || typeof value !== "object") return "";
  var fields = ["display_name", "item_name", "raw_name", "name", "label"];
  for (var i = 0; i < fields.length; i++) {
    if (value[fields[i]] !== undefined && value[fields[i]] !== null && String(value[fields[i]]).trim()) {
      return String(value[fields[i]]).trim();
    }
  }
  return "";
}

function buildPricedCoupons(couponNumbers, items, couponPlansByNumber) {
  var counts = {};
  var ordered = [];
  var numbers = Array.isArray(couponNumbers) ? couponNumbers : [];
  for (var i = 0; i < numbers.length; i++) {
    var key = String(numbers[i]);
    if (!counts[key]) ordered.push(key);
    counts[key] = (counts[key] || 0) + 1;
  }
  var result = [];
  for (var j = 0; j < ordered.length; j++) {
    var numberKey = ordered[j];
    var saved = couponPlansByNumber[numberKey] || {};
    var plans = Array.isArray(saved.coupon_plans) ? saved.coupon_plans : [];
    var plan = plans.length ? plans[0] : {};
    var fixedNames = [];
    var fixed = Array.isArray(plan.fixed_items) ? plan.fixed_items : [];
    for (var f = 0; f < fixed.length; f++) {
      var fixedName = firstCustomerFacingName(fixed[f]);
      if (fixedName && fixedNames.indexOf(fixedName) < 0) fixedNames.push(fixedName);
    }
    var selected = [];
    var sourceItems = Array.isArray(items) ? items : [];
    for (var k = 0; k < sourceItems.length; k++) {
      var item = sourceItems[k] || {};
      if (String(item.category || "") !== "coupon_component") continue;
      if (String(item.coupon_number || "") !== numberKey) continue;
      selected.push(safeClone(item));
    }
    var numberForSpeech = couponNumberDigitsForSpeech(numberKey);
    result.push({
      coupon_number: Number(numberKey),
      coupon_number_for_speech: numberForSpeech,
      coupon_spoken_label: numberForSpeech ? ("Coupon " + numberForSpeech) : ("Coupon " + numberKey),
      quantity: counts[numberKey],
      display_name: stripPricesForSpeech(firstCustomerFacingName(plan)) || ("Coupon " + numberKey),
      fixed_items: fixedNames,
      selected_components: selected
    });
  }
  return result;
}

function enrichCoupon999Plan(output) {
  if (!output || output.ok !== true || Number(output.coupon_number) !== 999) return output;
  output.coupon_999_contract = {
    top_level_coupon_numbers: [999],
    each_pizza_is_separate_line: true,
    component_category: "coupon_component",
    component_coupon_number: 999,
    component_choice_type: "pizza_choice",
    component_quantity: 1,
    minimum_pizza_lines: 2,
    default_cheese_item_name: "Ultimate 4-Cheese",
    never_use_ordinary_pizza_rows_for_coupon_999: true,
    never_combine_pizzas_with_quantity_2: true
  };
  output.coupon_999_agent_instruction = "Use one top-level coupon_numbers entry 999. Build each qualifying pizza as its own coupon_component line with coupon_number 999, choice_type pizza_choice, and quantity 1. Cheese/plain cheese means Ultimate 4-Cheese. Never send a coupon 999 pizza as category pizza.";
  return output;
}

function validateCoupon999CompilePayload(payload) {
  var numbers = Array.isArray(payload && payload.coupon_numbers) ? payload.coupon_numbers : [];
  var topLevelCount = 0;
  for (var i = 0; i < numbers.length; i++) {
    if (Number(numbers[i]) === 999) topLevelCount += 1;
  }

  var items = Array.isArray(payload && payload.items) ? payload.items : [];
  var components = [];
  var malformed = [];
  var ordinaryPizzaRows = [];

  for (var j = 0; j < items.length; j++) {
    var item = items[j] || {};
    var category = String(item.category || "");
    var itemCoupon = Number(item.coupon_number);
    var choiceType = String(item.choice_type || "");
    if (category === "pizza") ordinaryPizzaRows.push(j);
    var missingCouponNumberOn999Shape = topLevelCount > 0 && category === "coupon_component" && choiceType === "pizza_choice" && (item.coupon_number === undefined || item.coupon_number === null || String(item.coupon_number).trim() === "");
    if (itemCoupon === 999 || missingCouponNumberOn999Shape) {
      var valid = category === "coupon_component" && itemCoupon === 999 && choiceType === "pizza_choice" && item.quantity !== undefined && Number(item.quantity) === 1 && String(item.item_name || "").trim();
      if (valid) components.push(j);
      else malformed.push(j);
    }
  }

  if (topLevelCount === 0 && components.length === 0 && malformed.length === 0) return null;

  if (topLevelCount !== 1 || malformed.length > 0 || components.length < 2) {
    return {
      ok: false,
      tool: "compile_and_price_order",
      stage: "validate",
      error_code: "COUPON_999_LINE_STRUCTURE",
      problem: "Coupon 999 was not sent as one top-level coupon line plus at least two separate pizza_choice component lines.",
      retry_without_asking_customer: malformed.length > 0,
      do_not_ask_if_already_confirmed: true,
      preserve_ordinary_pizza_rows: true,
      first_missing_question: components.length < 2 ? "How would you like the next missing coupon 999 pizza? The deal requires at least two separate pizzas." : null,
      required_correction: {
        coupon_numbers: [999],
        each_pizza: {
          category: "coupon_component",
          coupon_number: 999,
          choice_type: "pizza_choice",
          item_name: "Use the exact chosen pizza name. Cheese/plain cheese means Ultimate 4-Cheese.",
          quantity: 1
        },
        minimum_pizza_lines: 2,
        one_pizza_per_line: true,
        do_not_use_category_pizza_for_coupon_999: true,
        do_not_use_quantity_2: true
      },
      received: {
        top_level_999_count: topLevelCount,
        valid_pizza_choice_lines: components.length,
        malformed_component_indexes: malformed,
        ordinary_pizza_indexes_do_not_count_for_coupon_999: ordinaryPizzaRows
      },
      next_step: malformed.length > 0
        ? "Repair the malformed coupon 999 component rows and resend the complete cart without asking the caller again. Preserve every ordinary pizza row."
        : "Preserve every ordinary pizza row. Build separate coupon_component pizza_choice lines from already confirmed coupon 999 choices. Ask the first_missing_question only when those coupon choices are not already known."
    };
  }

  return null;
}

function buildPickupLocationForReadback(output) {
  output = output && typeof output === "object" ? output : {};
  var display = stripCaliforniaForSpeech(output.store_display_location_for_customer || "");
  var address = stripCaliforniaForSpeech(output.store_address_for_customer || "");
  var landmark = String(output.store_landmark_for_customer || "").trim();

  if (display) {
    if (landmark && display.toLowerCase().indexOf(landmark.toLowerCase()) < 0) return display + ", " + landmark;
    if (!landmark && LAB_PICKUP_LANDMARK && display.toLowerCase().indexOf(LAB_PICKUP_LANDMARK.toLowerCase()) < 0) {
      return display + ", " + LAB_PICKUP_LANDMARK;
    }
    return display;
  }
  if (address) return address + ", " + (landmark || LAB_PICKUP_LANDMARK);
  return stripCaliforniaForSpeech(LAB_PICKUP_LOCATION_FOR_READBACK);
}

function formatCurrencyForSpeech(value) {
  var normalized = String(value === undefined || value === null ? "" : value).replace(/[$,]/g, "").trim();
  if (!normalized) return "";
  var amount = Number(normalized);
  return isFinite(amount) ? "$" + amount.toFixed(2) : "";
}

function buildFinalReadbackInstructions(modelOutput) {
  var location = String(modelOutput && modelOutput.pickup_location_for_readback || "").trim();
  var total = String(modelOutput && modelOutput.grand_total_for_speech || "").trim() || formatCurrencyForSpeech(modelOutput && modelOutput.grand_total);
  if (!location) {
    return "Do not give the final approval readback. The pickup store name, address, and landmark are missing.";
  }
  return [
    "Begin immediately with the first priced food item.",
    "Do not say Compiling and pricing that now. The compile-status sentence was already spoken.",
    "Read the complete priced order from priced_items and priced_coupons.",
    "For every priced coupon, say coupon_spoken_label exactly so the coupon number is spoken as separate digits. Never read a coupon number as a whole number.",
    "Do not state any individual item, coupon, package, unit, or line-item price.",
    "Then say the pickup store name, address, and landmark exactly: " + location,
    "Do not say California or C A.",
    "Then state only the grand total" + (total ? ": " + total : "") + ".",
    "End exactly with: Is everything correct?",
    "Stop and wait. After the caller approves, ask the exact payment-choice question from the main instructions. Do not submit yet."
  ].join("\n");
}


function readSecret(name) {
  try { return String(VoxEngine.getSecretValue(name) || "").trim(); }
  catch (e) { L("LAB_SECRET_READ_ERROR name=" + name + " error=" + e); return ""; }
}

function getProviderCallId(call) {
  try {
    if (call && typeof call.id === "function") return String(call.id());
    if (call && call.id) return String(call.id);
  } catch (_) {}
  return "voximplant-" + Date.now() + "-" + Math.floor(Math.random() * 1000000);
}

function redactLogValue(value) {
  if (Array.isArray(value)) return value.map(redactLogValue);
  if (!value || typeof value !== "object") return value;
  var out = {};
  for (var key in value) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
    if (/account|card_number|pan|token|cvv|security_code|auth|authid/i.test(key)) {
      out[key] = "[REDACTED]";
    } else {
      out[key] = redactLogValue(value[key]);
    }
  }
  return out;
}

function auditLog(type, data) {
  L("PMD_AUDIT " + JSON.stringify({ts: new Date().toISOString(), type: String(type || "event"), data: redactLogValue(data || {})}));
}

function makeCallLogBody(state, eventType, payload) {
  return {
    provider: "voximplant",
    provider_call_id: state.providerCallId,
    event_type: String(eventType || "event"),
    phone_number: state.callerPhone || null,
    payload: redactLogValue(payload || {})
  };
}

function queueCallLog(state, eventType, payload) {
  if (!state) return;
  if (!Array.isArray(state.callLogQueue)) state.callLogQueue = [];
  state.callLogQueue.push(makeCallLogBody(state, eventType, payload));
  if (state.callLogQueue.length > 300) state.callLogQueue.shift();
  if (LAB_CALL_LOG_FLUSH_DURING_CALL) flushCallLogs(state, false, "during_call");
}

function queueCompletedToolCallLog(state, name, callId, args, output, startedAtMs, startedAtIso) {
  var endedAtMs = Date.now();
  var result = output || {};
  queueCallLog(state, "tool_call", {
    tool_name: String(name || ""),
    provider_tool_call_id: String(callId || ""),
    request: args || {},
    response: result,
    success: Boolean(result && result.ok === true),
    error_message: result && result.ok === false ? String(result.error || result.message || "Tool failed") : null,
    started_at: String(startedAtIso || new Date(startedAtMs || endedAtMs).toISOString()),
    ended_at: new Date(endedAtMs).toISOString(),
    latency_ms: Math.max(0, endedAtMs - (startedAtMs || endedAtMs))
  });
}

function flushCallLogs(state, finalFlush, reason) {
  if (!state || state.callLogFlushInProgress) return;
  var queue = Array.isArray(state.callLogQueue) ? state.callLogQueue : [];
  if (!queue.length) return;
  var secret = readSecret("CALL_LOG_SECRET");
  if (!secret) {
    L("LAB_CALL_LOG_SKIPPED missing CALL_LOG_SECRET events=" + queue.length);
    return;
  }
  var batch = queue.splice(0, finalFlush ? queue.length : Math.min(queue.length, 20));
  state.callLogFlushInProgress = true;
  L("LAB_CALL_LOG_FLUSH reason=" + String(reason || "") + " events=" + batch.length + " remaining=" + queue.length);
  Net.httpRequestAsync(LAB_CALL_LOG_BATCH_URL, {
    method: "POST",
    headers: ["Content-Type: application/json", "x-call-log-secret: " + secret],
    postData: JSON.stringify({
      provider: "voximplant",
      provider_call_id: state.providerCallId,
      phone_number: state.callerPhone || null,
      events: batch
    })
  }).then(function (res) {
    state.callLogFlushInProgress = false;
    L("LAB_CALL_LOG_STATUS " + res.code + " events=" + batch.length);
    if (Number(res.code) === 207) {
      var responseText = String(res.text || res.body || res.data || "");
      L("LAB_CALL_LOG_207_BODY " + responseText);
    }
    if (finalFlush && state.callLogQueue.length) setTimeout(function () { flushCallLogs(state, true, "final_more"); }, 250);
  }).catch(function (err) {
    state.callLogFlushInProgress = false;
    L("LAB_CALL_LOG_ERROR " + String(err && err.message ? err.message : err));
  });
}

function normalizeSipReferDestination(rawValue) {
  var raw = String(rawValue || "").trim();
  if (!raw) return "";
  if (/^sip:/i.test(raw)) return raw;
  var match = raw.match(/^([^@\s]+)(?:@(.+))?$/);
  if (match) {
    var user = match[1].replace(/\D/g, "") || match[1];
    var host = match[2] || readSecret(LAB_TRANSFER_SIP_DOMAIN_SECRET) || LAB_TRANSFER_DEFAULT_SIP_DOMAIN;
    return "sip:" + user + "@" + host;
  }
  var digits = raw.replace(/\D/g, "");
  return digits ? "sip:" + digits + "@" + (readSecret(LAB_TRANSFER_SIP_DOMAIN_SECRET) || LAB_TRANSFER_DEFAULT_SIP_DOMAIN) : "";
}

function startSipReferTransfer(call, state, args) {
  var target = normalizeSipReferDestination(readSecret(LAB_TRANSFER_SIP_DESTINATION_SECRET));
  if (!target) return {ok: false, tool: "transfer_call", error: "Missing or invalid TRANSFER_SIP_DESTINATION.", next_step: "Tell the caller the transfer failed and keep helping."};
  if (state.transferInProgress) return {ok: true, tool: "transfer_call", status: "transfer_already_in_progress"};
  state.transferInProgress = true;
  state.transferTarget = target;
  var reason = String(args && args.reason || "live staff requested");
  L("LAB_SIP_REFER_START target=" + target + " reason=" + reason);
  auditLog("transfer_started", {target: target, reason: reason});
  queueCallLog(state, "transfer_started", {transfer_target: target, reason: reason});
  try {
    call.transferTo(target);
    return {ok: true, tool: "transfer_call", status: "sip_refer_transfer_requested", next_step: "Do not keep talking."};
  } catch (e) {
    state.transferInProgress = false;
    L("LAB_SIP_REFER_ERROR " + e);
    return {ok: false, tool: "transfer_call", error: String(e && e.message ? e.message : e), next_step: "Tell the caller the transfer failed and keep helping."};
  }
}

function transcriptLooksLikeQuestion(text) {
  var t = String(text || "").trim();
  return !!t && (/\?\s*$/.test(t) || /\b(is that right|anything else for the order|is everything correct|what can i get started|would you like to pay|which|what|how many|thin crust or pan style)\b/i.test(t));
}

function isFinalApprovalQuestion(text) {
  return /\bis everything correct\??\s*$/i.test(String(text || "").trim());
}

function buildSilenceRepromptText(question) {
  var q = String(question || "").replace(/\s+/g, " ").trim();
  var low = q.toLowerCase();
  if (/what can i get started/.test(low)) return "Still there? What can I get started for you today?";
  if (/is everything correct/.test(low)) return "Still there? Is everything correct?";
  if (/is that right/.test(low)) return "Still there? Is that right?";
  if (/anything else for the order/.test(low)) return "Still there? Anything else for the order?";
  if (/would you like to pay by card/.test(low)) return "Still there? Would you like to pay by card with me now, or pay at the store when you arrive?";
  if (!q || q.length > 110) return "Still there?";
  if (!/\?$/.test(q)) q += "?";
  return "Still there? " + q;
}

function cancelSilenceReprompt(state, reason) {
  if (!state) return;
  state.silenceGeneration += 1;
  if (state.silenceTimer) {
    try { clearTimeout(state.silenceTimer); } catch (_) {}
    state.silenceTimer = null;
  }
  state.pendingSilenceQuestion = "";
  state.pendingSilenceCreatedAt = 0;
  L("LAB_SILENCE_CANCEL reason=" + String(reason || ""));
}

function scheduleSilenceAfterQuestion(state, transcript) {
  cancelSilenceReprompt(state, "new_question");
  if (!transcriptLooksLikeQuestion(transcript)) return;
  state.pendingSilenceQuestion = String(transcript || "").trim();
  state.pendingSilenceCreatedAt = Date.now();
  state.pendingSilenceWaitingForMediaEnd = true;
  L("LAB_SILENCE_PENDING question=" + state.pendingSilenceQuestion);
}

function armPendingSilenceReprompt(vac, state) {
  if (!state.pendingSilenceQuestion || !state.pendingSilenceWaitingForMediaEnd) return;
  state.pendingSilenceWaitingForMediaEnd = false;
  var generation = ++state.silenceGeneration;
  var question = state.pendingSilenceQuestion;
  var createdAt = state.pendingSilenceCreatedAt;
  state.silenceTimer = setTimeout(function () {
    state.silenceTimer = null;
    if (state.callEnded || state.userSpeaking || state.responseInProgress || state.assistantAudioActive || state.transferInProgress) return;
    if (generation !== state.silenceGeneration) return;
    if (state.lastUserActivityAt > createdAt || state.lastToolActivityAt > createdAt) return;
    var forceText = buildSilenceRepromptText(question);
    L("LAB_SILENCE_FORCE_MESSAGE text=" + forceText);
    auditLog("silence_reprompt", {question: question, force_text: forceText});
    queueCallLog(state, "silence_reprompt", {question: question, force_text: forceText});
    state.lastSilenceForceText = forceText;
    state.suppressSilenceRearmUntil = Date.now() + 12000;
    state.responseInProgress = true;
    vac.conversationItemCreate({item: {type: "force_message", role: "assistant", interruptible: true, content: [{type: "output_text", text: forceText}]}});
  }, LAB_SILENCE_REPROMPT_MS);
  L("LAB_SILENCE_ARMED delay_ms=" + LAB_SILENCE_REPROMPT_MS + " question=" + question);
}



function maybeInstallAnythingElseMicrophase(vac, state, reason) {
  if (!vac || !state || state.callEnded || state.anythingElseMicrophaseStage !== "pending") return false;
  var sourceRecord = state.responses && state.responses[state.anythingElseMicrophaseSourceResponseId];
  if (!sourceRecord || !sourceRecord.done || sourceRecord.completedCalls < sourceRecord.expectedCalls) return false;
  if (sourceRecord.supersededByUser) {
    state.anythingElseMicrophaseStage = "";
    state.anythingElseMicrophaseSourceResponseId = "";
    L("LAB_ANYTHING_ELSE_EXACT_SKIPPED reason=superseded_by_user");
    return false;
  }
  if (state.responseInProgress || state.assistantAudioActive || state.userSpeaking) return false;
  state.anythingElseMicrophaseStage = "forcing";
  state.anythingElseMicrophaseResponseId = "";
  state.anythingElseMicrophaseExactSpoken = false;
  cancelSilenceReprompt(state, "anything_else_exact_force");
  state.responseInProgress = true;
  vac.conversationItemCreate({
    item: {
      type: "force_message",
      role: "assistant",
      interruptible: true,
      content: [{type: "output_text", text: "Anything else for the order?"}]
    }
  });
  L("LAB_ANYTHING_ELSE_EXACT_FORCE reason=" + String(reason || "") + " normal_tools_preserved=true");
  auditLog("anything_else_exact_force", {reason: reason || "", normal_tools_preserved: true});
  queueCallLog(state, "anything_else_exact_force", {reason: reason || "", normal_tools_preserved: true});
  return true;
}

function restoreMainAfterAnythingElseMicrophase(vac, state, reason) {
  if (!state) return false;
  var wasActive = Boolean(state.anythingElseMicrophaseStage);
  state.anythingElseMicrophaseStage = "";
  state.anythingElseMicrophaseSourceResponseId = "";
  state.anythingElseMicrophaseResponseId = "";
  state.anythingElseMicrophaseExactSpoken = false;
  if (wasActive) {
    L("LAB_ANYTHING_ELSE_EXACT_COMPLETE reason=" + String(reason || "") + " session_was_never_replaced=true");
    auditLog("anything_else_exact_complete", {reason: reason || "", session_was_never_replaced: true});
    queueCallLog(state, "anything_else_exact_complete", {reason: reason || "", session_was_never_replaced: true});
  }
  return wasActive;
}

function responseAssistantTranscript(response) {
  var output = response && Array.isArray(response.output) ? response.output : [];
  var parts = [];
  for (var i = 0; i < output.length; i++) {
    var item = output[i] || {};
    if (item.type !== "message" || item.role !== "assistant" || !Array.isArray(item.content)) continue;
    for (var j = 0; j < item.content.length; j++) {
      var content = item.content[j] || {};
      if (content.transcript) parts.push(String(content.transcript));
      else if (content.text) parts.push(String(content.text));
    }
  }
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function expectedAnnouncementForTool(name, args) {
  if (name === "get_coupon_plan") return "let me check that coupon";
  if (name === "compile_and_price_order") return "compiling and pricing that now";
  if (name === "submit_order") return "submitting that now";
  if (name === "transfer_call") return "i'll transfer you to a member of our team";
  if (name !== "get_ordering_catalog") return "";
  var category = String(args && args.category || "").toLowerCase();
  var query = String(args && args.item_query || "").toLowerCase();
  if (category === "pizza") return "let me check the pizza menu";
  if (category === "calzone") return "let me check calzone options";
  if (category === "subs" && /pizza\s*burger/.test(query)) return "let me check pizza burger options";
  if (category === "subs") return "let me check the sub menu";
  return "let me check";
}

function isOrderingTool(name) {
  return name === "get_ordering_catalog" || name === "get_coupon_plan" || name === "compile_and_price_order" || name === "submit_order";
}

function getCallerId(call) {
  try {
    if (call && typeof call.callerid === "function") return call.callerid();
    if (call && typeof call.callerid === "string") return call.callerid;
  } catch (_) {}
  return "";
}

function backendHeaders() {
  var headers = ["Content-Type: application/json"];
  try {
    var key = VoxEngine.getSecretValue("PMD_BACKEND_API_KEY") || "";
    if (key) headers.push("x-pmd-backend-key: " + key);
  } catch (e) {
    L("LAB_BACKEND_SECRET_ERROR " + e);
  }
  return headers;
}

async function postJson(url, payload) {
  logChunks("LAB_HTTP_REQUEST", {url: url, payload: redactLogValue(payload)});
  var response = await Net.httpRequestAsync(url, {
    method: "POST",
    headers: backendHeaders(),
    postData: JSON.stringify(payload || {})
  });
  L("LAB_HTTP_STATUS " + response.code + " url=" + url);
  var parsed;
  try { parsed = JSON.parse(response.text || "{}"); }
  catch (_) { parsed = {ok: response.code >= 200 && response.code < 300, raw: response.text || ""}; }
  logChunks("LAB_HTTP_RESULT", redactLogValue(parsed));
  if (response.code < 200 || response.code >= 300) {
    var httpError = new Error("HTTP " + response.code + ": " + String(response.text || ""));
    httpError.httpCode = response.code;
    httpError.parsedBody = parsed;
    throw httpError;
  }
  return parsed;
}

function toolOutput(vac, callId, output) {
  vac.conversationItemCreate({
    item: {
      type: "function_call_output",
      call_id: callId,
      output: JSON.stringify(output)
    }
  });
}

function addEvent(vac, eventName, handler) {
  if (!eventName) return;
  vac.addEventListener(eventName, handler);
}

function countFunctionCalls(response) {
  var output = response && Array.isArray(response.output) ? response.output : [];
  var count = 0;
  for (var i = 0; i < output.length; i++) {
    if (output[i] && output[i].type === "function_call") count += 1;
  }
  return count;
}

function sanitizeToolOutputForModel(name, output) {
  var clean = safeClone(output || {});

  if (name === "get_coupon_plan") {
    clean = stripPricesFromCustomerFacingStrings(clean);
    clean.spoken_price_policy = "Do not state individual, coupon, package, unit, or line-item prices unless the caller specifically asks.";
  }

  // The backend's compiled oneSystem payload is retained privately for submit_order.
  // Everything else from the customer-safe compiler result remains visible to Grok.
  if (name === "compile_and_price_order") {
    if (clean && clean.order_json) delete clean.order_json;
    if (clean && clean.order_json_string) delete clean.order_json_string;
    if (clean && clean.compiled_order_json) delete clean.compiled_order_json;
  }

  // A customer may hear the public order number, never internal backend identifiers.
  if (name === "get_payment_token") {
    clean = {
      ok: clean && clean.ok === true,
      tool: "get_payment_token",
      payment_token_saved: clean && clean.payment_token_saved === true,
      type_code: clean && clean.type_code ? clean.type_code : "",
      last4: clean && clean.last4 ? clean.last4 : "",
      error: clean && clean.ok === true ? "" : String(clean && clean.error || "")
    };
  }

  if (name === "submit_order") {
    if (clean && clean.order_id) delete clean.order_id;
    if (clean && clean.submitted_order_id) delete clean.submitted_order_id;
    if (clean && clean.backend_order_id) delete clean.backend_order_id;
    if (clean && clean.order_number && !clean.customer_facing_order_number) {
      clean.customer_facing_order_number = clean.order_number;
    }
    if (clean && clean.ok === true && clean.submitted === true) {
      clean = {
        ok: true,
        submitted: true,
        customer_facing_order_number: clean.customer_facing_order_number || "",
        pickup_estimate: clean.pickup_estimate || clean.quote_text || clean.quote || clean.quoted || "",
        submission_status: clean.submission_status || "SUBMITTED_LOCKED"
      };
    }
  }

  return clean;
}


function digitsOnly(value) { return String(value || "").replace(/\D/g, ""); }
function paymentQuestionText() { return "Would you like to pay by card with me now, or pay at the store when you arrive?"; }
function cardNumberPromptText() { return "Please enter the card number on your keypad. When you're done, say okay."; }
function cardExpirationPromptText() { return "Please enter the expiration date on your keypad as MMYY. When you're done, say okay."; }
function billingZipPromptText() { return "Please enter your billing ZIP code on your keypad. When you're done, say okay."; }
function paymentDoneSpeech(text) {
  var t = String(text || "").toLowerCase().replace(/[^a-z0-9' ]+/g, " ").replace(/\s+/g, " ").trim();
  return /^(okay|ok|done|finished|complete|that's all|that is all|all done|ready)$/.test(t);
}
function paymentTypeCodeFromCardNumber(value) {
  var d = digitsOnly(value);
  if (/^4/.test(d)) return "V";
  if (/^3[47]/.test(d)) return "X";
  if (/^(5[1-5]|2[2-7])/.test(d)) return "M";
  if (/^(6011|65|64[4-9])/.test(d)) return "R";
  return "";
}
function paymentCardNumberLengthAllowed(value) {
  var d = digitsOnly(value), tc = paymentTypeCodeFromCardNumber(d);
  if (tc === "V") return d.length === 13 || d.length === 16 || d.length === 19;
  if (tc === "X") return d.length === 15;
  if (tc === "M" || tc === "R") return d.length === 16;
  return false;
}
function luhnValid(value) {
  var d = digitsOnly(value);
  if (d.length < 13 || d.length > 19) return false;
  var sum = 0, dbl = false;
  for (var i = d.length - 1; i >= 0; i--) {
    var n = parseInt(d.charAt(i), 10);
    if (dbl) { n *= 2; if (n > 9) n -= 9; }
    sum += n; dbl = !dbl;
  }
  return sum % 10 === 0;
}
function acceptedPaymentCardNumber(value) { return paymentCardNumberLengthAllowed(value) && luhnValid(value); }
function validExpiration(value) {
  var d = digitsOnly(value);
  if (d.length !== 4) return false;
  var month = parseInt(d.slice(0, 2), 10);
  return month >= 1 && month <= 12;
}
function toolByName(name) {
  for (var i = 0; i < LAB_TOOLS.length; i++) if (LAB_TOOLS[i] && LAB_TOOLS[i].name === name) return LAB_TOOLS[i];
  return null;
}
function paymentTools(names) {
  var out = [];
  for (var i = 0; i < names.length; i++) { var t = toolByName(names[i]); if (t) out.push(t); }
  return out;
}
function sessionInfoForBackend(state) {
  var info = state && state.sessionInfo && typeof state.sessionInfo === "object" ? state.sessionInfo : {};
  return {
    store_number: info.store_number !== undefined && info.store_number !== null ? info.store_number : LAB_STORE_NUMBER,
    order_type: String(info.order_type || LAB_ORDER_TYPE),
    phone: String(info.phone || (state && state.callerPhone) || ""),
    customer_name: String(info.customer_name || "Lean Ordering Lab"),
    delivery: info.delivery && typeof info.delivery === "object" ? safeClone(info.delivery) : null,
    curbside: info.curbside && typeof info.curbside === "object" ? safeClone(info.curbside) : null
  };
}
function buildCompilePayloadFromSession(args, state) {
  var sessionInfo = sessionInfoForBackend(state);
  var payload = {
    store_number: sessionInfo.store_number,
    order_type: sessionInfo.order_type,
    phone: sessionInfo.phone,
    customer_name: sessionInfo.customer_name,
    items: Array.isArray(args && args.items) ? args.items : []
  };
  if (Array.isArray(args && args.coupon_numbers)) payload.coupon_numbers = args.coupon_numbers;
  else if (args && args.coupon_number !== undefined && args.coupon_number !== null) payload.coupon_number = args.coupon_number;
  if (sessionInfo.delivery) payload.delivery = sessionInfo.delivery;
  if (sessionInfo.curbside) payload.curbside = sessionInfo.curbside;
  return payload;
}
function normalizedIntentText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9' ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
function isPizzaBurgerQuery(value) {
  var t = normalizedIntentText(value);
  return t === "pizza burger" || t === "a pizza burger" || t === "the pizza burger";
}
function callerExplicitlyRequestedTransfer(value) {
  var t = normalizedIntentText(value);
  if (!t) return false;
  return (
    /\btransfer me\b/.test(t) ||
    /\btransfer (?:me )?(?:to )?(?:a |the )?(?:person|human|staff|team|manager|representative)\b/.test(t) ||
    /\bconnect me (?:to|with) (?:a |the )?(?:person|human|staff|team|manager|representative)\b/.test(t) ||
    /\b(?:can|could|may) i (?:speak|talk) (?:to|with) (?:a |the )?(?:person|human|staff|team|manager|representative)\b/.test(t) ||
    /\bi (?:want|need|would like) (?:to (?:speak|talk) (?:to|with) )?(?:a |the )?(?:person|human|staff member|manager|representative)\b/.test(t) ||
    /\bget me (?:a |the )?(?:person|human|staff member|manager|representative)\b/.test(t)
  );
}
function assistantAskedTransferPermission(value) {
  return normalizedIntentText(value).indexOf("would you like me to transfer you to a member of our team") >= 0;
}
function callerClearlyApprovedTransfer(value) {
  var t = normalizedIntentText(value);
  return /^(?:yes|yeah|yep|yup|sure|okay|ok|please do|go ahead|that is fine|that's fine)$/.test(t);
}
function transferConsentSatisfied(state) {
  if (!state) return false;
  if (callerExplicitlyRequestedTransfer(state.latestUserTranscript)) return true;
  return assistantAskedTransferPermission(state.lastAssistantTranscript) && callerClearlyApprovedTransfer(state.latestUserTranscript);
}
function paymentStagePrompt(state, stage) {
  var appendix = [];
  if (stage === "card_number") appendix = [
    "SECURE KEYPAD CARD NUMBER",
    "Runtime privately owns keypad digits and field validation. Never repeat digits.",
    "Normal conversation context and normal tools remain active. You alone interpret corrections, additions, reversals, and payment changes.",
    "For ordinary card entry, wait until Runtime advances the field after the caller says okay."
  ];
  else if (stage === "expiration") appendix = [
    "SECURE KEYPAD EXPIRATION",
    "Runtime privately owns keypad digits and field validation. Never repeat digits.",
    "Normal conversation context and normal tools remain active. You alone interpret corrections, additions, reversals, and payment changes.",
    "For ordinary expiration entry, wait until Runtime advances the field after the caller says okay."
  ];
  else if (stage === "zip") appendix = [
    "SECURE KEYPAD BILLING ZIP",
    "Runtime privately owns keypad digits and field validation. Never repeat digits.",
    "Normal conversation context and normal tools remain active. You alone interpret corrections, additions, reversals, and payment changes.",
    digitsOnly(state.paymentZipDigits).length === 5
      ? "When the caller says okay or done for the completed ZIP, say exactly: Processing. Then call get_payment_token in the same response."
      : "Wait until Runtime has a complete ZIP and the caller says okay."
  ];
  else if (stage === "processing") appendix = [
    "SECURE PAYMENT TOKENIZATION",
    "Normal conversation context and normal tools remain active.",
    "Call get_payment_token only for the completed private card fields. The caller may still correct the order or switch payment before successful submission."
  ];
  else if (stage === "token_success") appendix = [
    "PAYMENT TOKEN SAVED",
    "Normal conversation context and normal tools remain active.",
    "For card submission, say exactly: Submitting that now. Then call submit_order with payment_method card.",
    "If the caller instead switches to pay at store, call submit_order with payment_method pay_at_store."
  ];
  else if (stage === "pay_at_store_submit") appendix = [
    "PAY AT STORE SELECTED",
    "Normal conversation context and normal tools remain active.",
    "Say exactly: Submitting that now. Then call submit_order with payment_method pay_at_store."
  ];
  else appendix = [
    "NORMAL LANGUAGE DECISION",
    "You alone interpret the caller's answer. Runtime does not classify it with phrase lists."
  ];
  return LAB_PROMPT + "\n\n" + appendix.join("\n");
}
function installPaymentStage(vac, state, stage, reason) {
  state.paymentStage = stage;
  var signature = stage + (stage === "zip" ? "|" + digitsOnly(state.paymentZipDigits).length : "");
  if (state.paymentStageSignature === signature) return;
  state.paymentStageSignature = signature;
  state.paymentStageUpdatePending = true;
  var stageTurnDetection = stage === "final_approval"
    ? {type: "server_vad", threshold: 0.5, prefix_padding_ms: 200, silence_duration_ms: 650}
    : {type: "server_vad", threshold: 0.65, prefix_padding_ms: 200, silence_duration_ms: 300};
  vac.sessionUpdate({session: {
    turn_detection: stageTurnDetection,
    tool_choice: "auto",
    parallel_tool_calls: false,
    keep_context: true,
    instructions: paymentStagePrompt(state, stage),
    tools: LAB_TOOLS,
    voice: "ara",
    reasoning: {effort: LAB_REASONING_EFFORT}
  }});
  L("LAB_PAYMENT_STAGE stage=" + stage + " reason=" + String(reason || "") + " tools=ALL_NORMAL_TOOLS");
  auditLog("payment_stage", {stage: stage, reason: reason || "", tools: "ALL_NORMAL_TOOLS", agent_owns_language_decision: true});
  queueCallLog(state, "payment_stage", {stage: stage, reason: reason || "", tools: "ALL_NORMAL_TOOLS", agent_owns_language_decision: true});
}

function restoreMainSession(vac, state, reason) {
  state.paymentStage = "";
  state.paymentStageSignature = "";
  state.paymentStageUpdatePending = false;
  state.pendingRuntimePaymentAction = null;
  state.suppressNextPaymentAutoResponse = false;
  state.processingAutoResponseCancelPending = false;
  state.processingAutoResponseId = "";
  vac.sessionUpdate({session: {
    turn_detection: {type: "server_vad", threshold: 0.5, prefix_padding_ms: 200, silence_duration_ms: 650},
    tool_choice: "auto", parallel_tool_calls: false, keep_context: true,
    instructions: LAB_PROMPT, tools: LAB_TOOLS, voice: "ara", reasoning: {effort: LAB_REASONING_EFFORT}
  }});
  L("LAB_PAYMENT_STAGE_RESTORE reason=" + String(reason || ""));
}
function beginCardCapture(vac, state, reason) {
  if (state.paymentDtmfMode && state.paymentStage === "card_number") return;
  state.paymentChoice = "card";
  state.awaitingPaymentChoice = false;
  state.paymentDtmfMode = true;
  state.paymentDtmfDigits = "";
  state.paymentExpDigits = "";
  state.paymentZipDigits = "";
  state.paymentCardAccount = "";
  state.paymentCardExpdate = "";
  state.paymentBillingZip = "";
  state.paymentInfo = null;
  state.pendingForcedCardPrompt = true;
  installPaymentStage(vac, state, "card_number", reason || "caller_selected_card");
}


function resetCardStateForPayAtStore(state, reason) {
  if (!state) return;
  if (state.runtimePaymentActionTimer) {
    try { clearTimeout(state.runtimePaymentActionTimer); } catch (_) {}
    state.runtimePaymentActionTimer = null;
  }
  state.awaitingPaymentChoice = false;
  state.paymentDtmfMode = false;
  state.pendingForcedCardPrompt = false;
  state.pendingRuntimePaymentAction = null;
  state.suppressNextPaymentAutoResponse = false;
  state.processingAutoResponseCancelPending = false;
  state.processingAutoResponseId = "";
  state.paymentDtmfDigits = "";
  state.paymentExpDigits = "";
  state.paymentZipDigits = "";
  state.paymentCardAccount = "";
  state.paymentCardExpdate = "";
  state.paymentBillingZip = "";
  state.paymentInfo = null;
  L("LAB_PAY_AT_STORE_CARD_STATE_RESET reason=" + String(reason || "") + " priced_order_preserved=" + Boolean(state.lastPricedOrderJson));
  auditLog("pay_at_store_card_state_reset", {reason: reason || "", priced_order_preserved: Boolean(state.lastPricedOrderJson)});
  queueCallLog(state, "pay_at_store_card_state_reset", {reason: reason || "", priced_order_preserved: Boolean(state.lastPricedOrderJson)});
}

function switchPaymentToPayAtStore(vac, state, reason, installSubmitStage) {
  if (!state || state.submitted) return false;
  resetCardStateForPayAtStore(state, reason || "caller_switched_to_pay_at_store");
  state.paymentChoice = "pay_at_store";
  state.awaitingPaymentChoice = false;
  if (installSubmitStage === true) installPaymentStage(vac, state, "pay_at_store_submit", reason || "agent_selected_pay_at_store");
  L("LAB_PAYMENT_SWITCH pay_at_store reason=" + String(reason || ""));
  auditLog("payment_switch", {choice: "pay_at_store", reason: reason || ""});
  queueCallLog(state, "payment_switch", {choice: "pay_at_store", reason: reason || ""});
  return true;
}

function submissionHasOrderEvidence(output) {
  if (!output || typeof output !== "object") return false;
  if (output.submitted === true) return true;
  var fields = ["customer_facing_order_number", "order_number", "order_id", "submitted_order_id", "backend_order_id"];
  for (var i = 0; i < fields.length; i++) {
    if (output[fields[i]] !== undefined && output[fields[i]] !== null && String(output[fields[i]]).trim()) return true;
  }
  return false;
}
function submissionFailureIsConfirmed(output) {
  if (!output || typeof output !== "object" || submissionHasOrderEvidence(output)) return false;
  return output.submitted === false || output.ok === false;
}
function submittedOrderLockedPrompt() {
  return [
    "ORDER STATUS: SUBMITTED AND LOCKED",
    "oneSystem confirmed that this order was created. It can never be submitted again by this AI.",
    "You cannot modify, add to, remove from, cancel, or resubmit this submitted order, and you cannot add or change its payment.",
    "If the caller asks for any change or payment action on this submitted order, say exactly: I'll transfer you to a member of our team. Please stay on the line. Then call transfer_call.",
    "Do not call ordering, compile, payment-token, or submit tools."
  ].join("\n");
}
function submissionUnknownPrompt() {
  return [
    "ORDER STATUS: SUBMISSION RESULT UNKNOWN",
    "The submit request may or may not have created the order. Never retry submit because that could create a duplicate.",
    "Say exactly: I'll transfer you to a member of our team. Please stay on the line. Then call transfer_call.",
    "Do not call ordering, compile, payment-token, or submit tools."
  ].join("\n");
}
function installSubmissionTerminalSession(vac, state, status, reason) {
  if (!vac || !state || state.callEnded) return;
  state.submissionStatus = status;
  state.paymentStage = "";
  state.paymentStageSignature = "";
  state.paymentStageUpdatePending = false;
  state.awaitingPaymentChoice = false;
  state.paymentDtmfMode = false;
  state.pendingForcedCardPrompt = false;
  vac.sessionUpdate({session: {
    turn_detection: {type: "server_vad", threshold: 0.5, prefix_padding_ms: 200, silence_duration_ms: 650},
    tool_choice: "auto",
    parallel_tool_calls: false,
    keep_context: true,
    instructions: status === "SUBMITTED_LOCKED" ? submittedOrderLockedPrompt() : submissionUnknownPrompt(),
    tools: paymentTools(["transfer_call"]),
    voice: "ara",
    reasoning: {effort: LAB_REASONING_EFFORT}
  }});
  L("LAB_SUBMISSION_TERMINAL_SESSION status=" + status + " reason=" + String(reason || "") + " tools=transfer_call");
  auditLog("submission_terminal_session", {status: status, reason: reason || "", tools: ["transfer_call"]});
  queueCallLog(state, "submission_terminal_session", {status: status, reason: reason || "", tools: ["transfer_call"]});
}
function classifySubmitException(error) {
  var parsed = error && error.parsedBody && typeof error.parsedBody === "object" ? safeClone(error.parsedBody) : null;
  if (parsed && submissionHasOrderEvidence(parsed)) return {status: "SUBMITTED_LOCKED", output: parsed};
  if (parsed && submissionFailureIsConfirmed(parsed)) return {status: "RETRYABLE", output: parsed};
  return {
    status: "SUBMISSION_UNKNOWN",
    output: {
      ok: false,
      submitted: false,
      submission_unknown: true,
      error_code: "SUBMISSION_RESULT_UNKNOWN",
      error: "The submission result could not be verified. Do not retry; transfer to staff."
    }
  };
}

function forceExactPaymentPrompt(vac, state, prompt, label) {
  if (!prompt || state.callEnded) return;
  cancelSilenceReprompt(state, label || "runtime_payment_prompt");
  try {
    if (vac.clearMediaBuffer) vac.clearMediaBuffer();
    if (vac.responseCancel) vac.responseCancel();
  } catch (e) {
    L("LAB_RUNTIME_PAYMENT_PROMPT_CANCEL_ERROR " + e);
  }
  state.responseInProgress = false;
  state.assistantAudioActive = false;
  L("LAB_RUNTIME_PAYMENT_PROMPT force=" + String(label || "payment") + " text=" + prompt);
  auditLog("runtime_payment_prompt", {label: label || "payment", prompt: prompt});
  queueCallLog(state, "runtime_payment_prompt", {label: label || "payment", prompt: prompt});
  setTimeout(function () {
    if (state.callEnded) return;
    state.responseInProgress = true;
    vac.conversationItemCreate({
      item: {
        type: "force_message",
        role: "assistant",
        interruptible: true,
        content: [{type: "output_text", text: prompt}]
      }
    });
  }, 25);
}
function maybeRunRuntimePaymentAction(vac, state, reason) {
  if (!state.pendingRuntimePaymentAction) return;
  if (state.paymentStageUpdatePending || state.suppressNextPaymentAutoResponse) return;
  if (state.pendingRuntimePaymentAction.type === "processing" &&
      (state.processingAutoResponseCancelPending || state.responseInProgress || state.assistantAudioActive)) return;
  var action = state.pendingRuntimePaymentAction;
  state.pendingRuntimePaymentAction = null;
  if (state.runtimePaymentActionTimer) {
    try { clearTimeout(state.runtimePaymentActionTimer); } catch (_) {}
    state.runtimePaymentActionTimer = null;
  }
  L("LAB_RUNTIME_PAYMENT_ACTION type=" + action.type + " reason=" + String(reason || ""));
  if (action.type === "prompt") {
    forceExactPaymentPrompt(vac, state, action.text, action.label);
  } else if (action.type === "processing") {
    vac.responseCreate({response: {instructions: 'Say exactly: "Processing." Then call get_payment_token. Call no other tool. Say nothing else.'}});
  }
}
function queueRuntimePaymentAction(vac, state, action) {
  state.pendingRuntimePaymentAction = action;
  state.suppressNextPaymentAutoResponse = true;
  if (action && action.type === "processing" && state.responseInProgress) {
    state.processingAutoResponseCancelPending = true;
    state.suppressNextPaymentAutoResponse = false;
    L("LAB_RUNTIME_PROCESSING_STALE_RESPONSE_CANCEL reason=already_in_progress");
    auditLog("runtime_processing_stale_response_cancel", {reason: "already_in_progress"});
    try {
      if (vac.clearMediaBuffer) vac.clearMediaBuffer();
      if (vac.responseCancel) vac.responseCancel();
    } catch (processingCancelErr) {
      L("LAB_RUNTIME_PROCESSING_STALE_RESPONSE_CANCEL_ERROR " + processingCancelErr);
    }
  }
  if (state.runtimePaymentActionTimer) {
    try { clearTimeout(state.runtimePaymentActionTimer); } catch (_) {}
  }
  state.runtimePaymentActionTimer = setTimeout(function () {
    if (!state.pendingRuntimePaymentAction || state.callEnded) return;
    if (state.suppressNextPaymentAutoResponse) {
      try {
        if (vac.clearMediaBuffer) vac.clearMediaBuffer();
        if (vac.responseCancel) vac.responseCancel();
      } catch (_) {}
      state.responseInProgress = false;
      state.assistantAudioActive = false;
      state.suppressNextPaymentAutoResponse = false;
      L("LAB_RUNTIME_PAYMENT_AUTO_RESPONSE fallback_cancel=true");
    }
    maybeRunRuntimePaymentAction(vac, state, "fallback_timer");
  }, 500);
}
function commitRuntimePaymentField(vac, state, transcript) {
  if (!state || !paymentDoneSpeech(transcript)) return false;
  if (state.paymentStage === "card_number") {
    var cardDigits = digitsOnly(state.paymentDtmfDigits);
    if (acceptedPaymentCardNumber(cardDigits)) {
      state.paymentCardAccount = cardDigits;
      state.paymentDtmfDigits = "";
      state.paymentDtmfMode = false;
      auditLog("dtmf_card_commit", {digits_len: cardDigits.length, result: "valid", type_code: paymentTypeCodeFromCardNumber(cardDigits)});
      queueRuntimePaymentAction(vac, state, {type: "prompt", text: cardExpirationPromptText(), label: "card_number_committed"});
      installPaymentStage(vac, state, "expiration", "runtime_card_number_committed");
    } else {
      auditLog("dtmf_card_commit", {digits_len: cardDigits.length, result: "invalid"});
      state.paymentDtmfDigits = "";
      state.paymentCardAccount = "";
      queueRuntimePaymentAction(vac, state, {type: "prompt", text: cardNumberPromptText(), label: "card_number_invalid"});
    }
    return true;
  }
  if (state.paymentStage === "expiration") {
    var expDigits = digitsOnly(state.paymentExpDigits);
    if (validExpiration(expDigits)) {
      state.paymentCardExpdate = expDigits;
      state.paymentExpDigits = "";
      auditLog("dtmf_expdate_commit", {digits_len: expDigits.length, result: "valid"});
      queueRuntimePaymentAction(vac, state, {type: "prompt", text: billingZipPromptText(), label: "expiration_committed"});
      installPaymentStage(vac, state, "zip", "runtime_expiration_committed");
    } else {
      auditLog("dtmf_expdate_commit", {digits_len: expDigits.length, result: "invalid"});
      state.paymentExpDigits = "";
      queueRuntimePaymentAction(vac, state, {type: "prompt", text: cardExpirationPromptText(), label: "expiration_invalid"});
    }
    return true;
  }
  if (state.paymentStage === "zip") {
    var zipDigits = digitsOnly(state.paymentZipDigits).slice(0, 5);
    if (zipDigits.length === 5) {
      state.paymentBillingZip = zipDigits;
      auditLog("dtmf_zip_commit", {digits_len: zipDigits.length, result: "valid"});
    } else {
      auditLog("dtmf_zip_commit", {digits_len: zipDigits.length, result: "invalid"});
      state.paymentZipDigits = "";
      state.paymentBillingZip = "";
      queueRuntimePaymentAction(vac, state, {type: "prompt", text: billingZipPromptText(), label: "billing_zip_invalid"});
    }
    return true;
  }
  return false;
}

function forceExactCardNumberPrompt(vac, state) {
  if (!state.pendingForcedCardPrompt || state.paymentStage !== "card_number" || state.callEnded) return;
  state.pendingForcedCardPrompt = false;
  cancelSilenceReprompt(state, "card_prompt_force");
  try {
    if (vac.clearMediaBuffer) vac.clearMediaBuffer();
    if (vac.responseCancel) vac.responseCancel();
  } catch (e) {
    L("LAB_CARD_PROMPT_CANCEL_ERROR " + e);
  }
  state.responseInProgress = false;
  state.assistantAudioActive = false;
  var prompt = cardNumberPromptText();
  L("LAB_CARD_PROMPT_FORCE_MESSAGE");
  auditLog("card_prompt_forced", {prompt: prompt});
  queueCallLog(state, "card_prompt_forced", {prompt: prompt});
  setTimeout(function () {
    if (state.callEnded || state.paymentStage !== "card_number") return;
    state.responseInProgress = true;
    vac.conversationItemCreate({
      item: {
        type: "force_message",
        role: "assistant",
        interruptible: true,
        content: [{type: "output_text", text: prompt}]
      }
    });
  }, 25);
}
function extractTone(e) {
  e = e || {};
  var a = [e.tone, e.digit, e.digits, e.key, e.symbol, e.dtmf, e.code];
  for (var i = 0; i < a.length; i++) {
    if (a[i] === 0) return "0";
    var s = String(a[i] || "").trim();
    if (/^[0-9#*]$/.test(s)) return s;
    var m = s.match(/[0-9#*]/); if (m) return m[0];
  }
  return "";
}
function handlePaymentTone(vac, state, tone) {
  if (!state || !state.paymentStage) return false;
  var s = String(tone || "");
  if (!s) return false;
  if (state.paymentStage === "card_number") {
    if (s === "*") {
      state.paymentDtmfDigits = "";
      auditLog("dtmf_card_clear", {digits_len: 0, result: "cleared"});
    } else if (s === "#") {
      auditLog("dtmf_card_pound_ignored", {digits_len: digitsOnly(state.paymentDtmfDigits).length, result: "ignored"});
    } else if (/^[0-9]$/.test(s)) {
      state.paymentDtmfDigits = (state.paymentDtmfDigits + s).slice(0, 19);
      auditLog("dtmf_card_progress", {digits_len: digitsOnly(state.paymentDtmfDigits).length, ready: acceptedPaymentCardNumber(state.paymentDtmfDigits)});
    }
    return true;
  }
  if (state.paymentStage === "expiration") {
    if (s === "*") {
      state.paymentExpDigits = "";
      auditLog("dtmf_expdate_clear", {digits_len: 0, result: "cleared"});
    } else if (s === "#") {
      auditLog("dtmf_expdate_pound_ignored", {digits_len: digitsOnly(state.paymentExpDigits).length, result: "ignored"});
    } else if (/^[0-9]$/.test(s)) {
      state.paymentExpDigits = (state.paymentExpDigits + s).slice(0, 4);
      auditLog("dtmf_expdate_progress", {digits_len: digitsOnly(state.paymentExpDigits).length, ready: validExpiration(state.paymentExpDigits)});
    }
    return true;
  }
  if (state.paymentStage === "zip") {
    if (s === "*") {
      state.paymentZipDigits = "";
      auditLog("dtmf_zip_clear", {digits_len: 0, result: "cleared"});
    } else if (s === "#") {
      auditLog("dtmf_zip_pound_ignored", {digits_len: digitsOnly(state.paymentZipDigits).length, result: "ignored"});
    } else if (/^[0-9]$/.test(s)) {
      state.paymentZipDigits = (state.paymentZipDigits + s).slice(0, 5);
      auditLog("dtmf_zip_progress", {digits_len: digitsOnly(state.paymentZipDigits).length, ready: digitsOnly(state.paymentZipDigits).length === 5});
    }
    installPaymentStage(vac, state, "zip", "dtmf_tone");
    return true;
  }
  return false;
}
function attachPaymentToneListeners(call, vac, state) {
  var events = [];
  if (typeof CallEvents !== "undefined") {
    if (CallEvents.ToneReceived) events.push(CallEvents.ToneReceived);
    if (CallEvents.DTMFReceived) events.push(CallEvents.DTMFReceived);
    if (CallEvents.DTMF) events.push(CallEvents.DTMF);
  }
  var seen = {};
  for (var i = 0; i < events.length; i++) {
    var ev = events[i]; if (!ev || seen[String(ev)]) continue; seen[String(ev)] = true;
    call.addEventListener(ev, function (e) { var tone = extractTone(e); if (tone) handlePaymentTone(vac, state, tone); });
  }
  L("LAB_DTMF_LISTENERS count=" + events.length);
}
function paymentInfoFromToken(output, state) {
  if (!output || output.ok !== true || !output.token) return null;
  return {
    type_code: String(output.type_code || paymentTypeCodeFromCardNumber(state.paymentCardAccount) || ""),
    token: String(output.token),
    holder: String(output.holder || output.name || "Lean Ordering Lab"),
    expires: String(output.expires || output.expdate || state.paymentCardExpdate || ""),
    amount: state.lastPricedTotal !== null && state.lastPricedTotal !== undefined ? Number(state.lastPricedTotal).toFixed(2) : undefined,
    zip: String(output.zip || output.bzip || state.paymentBillingZip || ""),
    auth: output.auth ? String(output.auth) : undefined,
    authid: output.authid ? String(output.authid) : undefined,
    last4: String(output.last4 || digitsOnly(state.paymentCardAccount).slice(-4))
  };
}

VoxEngine.addEventListener(AppEvents.CallAlerting, async function (event) {
  var call = event.call;
  try {
    if (call && typeof call.handleTones === "function") {
      if (typeof DTMFType !== "undefined" && DTMFType.ALL) call.handleTones(true, DTMFType.ALL);
      else call.handleTones(true);
      L("LAB_DTMF handleTones enabled before answer");
    }
  } catch (toneEnableErr) {
    L("LAB_DTMF handleTones enable failed: " + toneEnableErr);
  }
  call.answer();

  var callerPhone = normalizePhone(getCallerId(call));
  var state = {
    mediaConnected: false,
    openingSent: false,
    assistantAudioActive: false,
    responseInProgress: false,
    continuationScheduled: false,
    continuationTimer: null,
    lastResponseDoneAt: 0,
    callEnded: false,
    userSpeaking: false,
    inputEpoch: 0,
    userTurnSerial: 0,
    latestUserTranscript: "",
    responseOrder: [],
    responses: {},
    lastPricedOrderJson: null,
    lastPricedTotal: null,
    lastPricedItems: [],
    lastPricedCouponNumbers: [],
    couponPlansByNumber: {},
    submitted: false,
    submissionStatus: "",
    submissionAttemptSerial: 0,
    submissionLastError: "",
    providerCallId: getProviderCallId(call),
    callerPhone: callerPhone,
    callStartedAt: Date.now(),
    callLogQueue: [],
    callLogFlushInProgress: false,
    transferInProgress: false,
    transferTarget: "",
    silenceGeneration: 0,
    silenceTimer: null,
    pendingSilenceQuestion: "",
    pendingSilenceCreatedAt: 0,
    pendingSilenceWaitingForMediaEnd: false,
    lastUserActivityAt: 0,
    lastToolActivityAt: 0,
    lastAssistantTranscript: "",
    anythingElseMicrophaseStage: "",
    anythingElseMicrophaseSourceResponseId: "",
    anythingElseMicrophaseResponseId: "",
    anythingElseMicrophaseExactSpoken: false,
    lastSilenceForceText: "",
    suppressSilenceRearmUntil: 0,
    awaitingPaymentChoice: false,
    paymentChoice: "",
    paymentStage: "",
    paymentStageSignature: "",
    paymentStageUpdatePending: false,
    pendingRuntimePaymentAction: null,
    runtimePaymentActionTimer: null,
    suppressNextPaymentAutoResponse: false,
    processingAutoResponseCancelPending: false,
    processingAutoResponseId: "",
    paymentDtmfMode: false,
    pendingForcedCardPrompt: false,
    paymentDtmfDigits: "",
    paymentExpDigits: "",
    paymentZipDigits: "",
    paymentCardAccount: "",
    paymentCardExpdate: "",
    paymentBillingZip: "",
    paymentInfo: null,
    sessionInfo: {
      store_number: LAB_STORE_NUMBER,
      order_type: LAB_ORDER_TYPE,
      phone: callerPhone,
      customer_name: "Lean Ordering Lab",
      delivery: null,
      curbside: null
    },
  };

  L("LAB_CALL_START provider_call_id=" + state.providerCallId + " caller=" + callerPhone);
  auditLog("call_started", {provider_call_id: state.providerCallId, phone_number: callerPhone, model: LAB_MODEL, reasoning_effort: LAB_REASONING_EFFORT, boot: LAB_BOOT});
  queueCallLog(state, "call_started", {started_at: new Date(state.callStartedAt).toISOString(), model: LAB_MODEL, reasoning_effort: LAB_REASONING_EFFORT, boot: LAB_BOOT, store_number: LAB_STORE_NUMBER, order_type: LAB_ORDER_TYPE});

  function getResponseRecord(responseId) {
    var id = String(responseId || "unknown");
    if (!state.responses[id]) {
      state.responses[id] = {
        id: id,
        done: false,
        expectedCalls: 0,
        startedCalls: 0,
        completedCalls: 0,
        calls: {},
        continuationSent: false,
        suppressContinuation: false,
        supersededByUser: false,
        continuationInstructions: "",
        inputEpoch: state.inputEpoch,
        userTurnSerial: state.userTurnSerial,
        firstOrderingToolCallId: "",
        firstOrderingToolName: "",
        orderingToolViolationCount: 0
      };
      state.responseOrder.push(id);
    }
    return state.responses[id];
  }

  function findReadyToolResponse() {
    for (var i = 0; i < state.responseOrder.length; i++) {
      var record = state.responses[state.responseOrder[i]];
      if (!record || record.continuationSent || record.suppressContinuation || record.supersededByUser || !record.done) continue;
      if (record.inputEpoch !== state.inputEpoch) continue;
      if (record.expectedCalls < 1) continue;
      if (record.completedCalls < record.expectedCalls) continue;
      return record;
    }
    return null;
  }

  L("BOOT_CLEAN_LAB " + LAB_BOOT);
  L("LAB_MODEL " + LAB_MODEL + " reasoning_effort=" + LAB_REASONING_EFFORT);
  L("LAB_FIXED_CONTEXT store_number=" + LAB_STORE_NUMBER + " order_type=" + LAB_ORDER_TYPE + " phone=" + callerPhone + " submit_mode=pay_at_store_or_card card_capture=dtmf_number_expdate_zip tool_contract=one_active_item+one_ordering_tool+announced_lookup+coupon_plan+dependent_coupon_options+anything_else_exact_force_normal_tools+agent_language_decisions+atomic_submission_lock+999_validation+priced_readback+silence+logging+transfer");
  logChunks("LAB_PROMPT", LAB_PROMPT);
  logChunks("LAB_TOOLS", LAB_TOOLS);

  var vac;
  try {
    vac = await Grok.createVoiceAgentAPIClient({
      xAIApiKey: VoxEngine.getSecretValue("GROK_API_KEY"),
      model: LAB_MODEL,
      onWebSocketClose: function (closeEvent) {
        L("LAB_GROK_WEBSOCKET_CLOSED " + JSON.stringify(closeEvent || {}));
        auditLog("grok_websocket_closed", {event: closeEvent || {}});
        queueCallLog(state, "grok_websocket_closed", {event: closeEvent || {}});
        if (!state.callEnded && !state.transferInProgress) {
          var target = normalizeSipReferDestination(readSecret(LAB_TRANSFER_SIP_DESTINATION_SECRET));
          if (target) {
            state.transferInProgress = true;
            state.transferTarget = target;
            L("LAB_GROK_WS_FAILOVER_TRANSFER target=" + target);
            queueCallLog(state, "grok_ws_failover_transfer", {transfer_target: target});
            try { call.transferTo(target); return; }
            catch (e) { state.transferInProgress = false; L("LAB_GROK_WS_FAILOVER_ERROR " + e); }
          }
          VoxEngine.terminate();
        }
      }
    });
  } catch (e) {
    L("LAB_GROK_CLIENT_ERROR " + e);
    try { call.hangup(); } catch (_) {}
    VoxEngine.terminate();
    return;
  }

  attachPaymentToneListeners(call, vac, state);

  function maybeContinueAfterTools(reason) {
    if (state.continuationScheduled) return;
    var ready = findReadyToolResponse();
    if (!ready) return;
    if (state.assistantAudioActive || state.responseInProgress) {
      L("LAB_TOOL_CONTINUATION_WAIT reason=" + reason + " response_id=" + ready.id + " audio=" + state.assistantAudioActive + " response=" + state.responseInProgress + " completed=" + ready.completedCalls + "/" + ready.expectedCalls);
      return;
    }

    state.continuationScheduled = true;
    state.continuationTimer = setTimeout(function () {
      state.continuationTimer = null;
      var stillReady = findReadyToolResponse();
      if (!stillReady || state.userSpeaking || state.assistantAudioActive || state.responseInProgress || state.callEnded) {
        state.continuationScheduled = false;
        if (!state.userSpeaking) maybeContinueAfterTools("retry");
        return;
      }
      stillReady.continuationSent = true;
      state.continuationScheduled = false;
      state.responseInProgress = true;
      L("LAB_RESPONSE_CREATE_AFTER_ALL_TOOL_OUTPUTS response_id=" + stillReady.id + " calls=" + stillReady.completedCalls + " user_turn=" + stillReady.userTurnSerial + " epoch=" + stillReady.inputEpoch + " custom_instructions=" + Boolean(stillReady.continuationInstructions));
      if (stillReady.continuationInstructions) {
        vac.responseCreate({response: {instructions: stillReady.continuationInstructions}});
      } else {
        vac.responseCreate({response: {}});
      }
    }, 120);
  }

  addEvent(vac, Grok.VoiceAgentAPIEvents.ConversationCreated, function () {
    L("LAB_CONVERSATION_CREATED");
    vac.sessionUpdate({
      session: {
        turn_detection: {
          type: "server_vad",
          threshold: 0.5,
          prefix_padding_ms: 200,
          silence_duration_ms: 650
        },
        tool_choice: "auto",
        parallel_tool_calls: false,
        instructions: LAB_PROMPT,
        tools: LAB_TOOLS,
        voice: "ara",
        reasoning: {effort: LAB_REASONING_EFFORT}
      }
    });
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.SessionUpdated, function () {
    L("LAB_SESSION_UPDATED");
    if (state.paymentStageUpdatePending) state.paymentStageUpdatePending = false;
    if (state.pendingForcedCardPrompt && state.paymentStage === "card_number") {
      forceExactCardNumberPrompt(vac, state);
    }
    maybeRunRuntimePaymentAction(vac, state, "session_updated");
    maybeContinueAfterTools("session_updated");
    if (!state.mediaConnected) {
      VoxEngine.sendMediaBetween(call, vac);
      state.mediaConnected = true;
      L("LAB_MEDIA_CONNECTED");
    }
    if (!state.openingSent) {
      state.openingSent = true;
      setTimeout(function () {
        L("LAB_OPENING_FORCE_MESSAGE");
        vac.conversationItemCreate({
          item: {
            type: "force_message",
            role: "assistant",
            interruptible: true,
            content: [{type: "output_text", text: "What can I get started for you today?"}]
          }
        });
      }, 250);
    }
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.ResponseCreated, function (e) {
    state.responseInProgress = true;
    var createdPayload = e && e.data && e.data.payload ? e.data.payload : {};
    var createdResponse = createdPayload.response || {};
    var createdPaymentResponseId = String(createdResponse.id || createdPayload.response_id || "unknown");
    if (state.processingAutoResponseCancelPending) {
      state.processingAutoResponseId = createdPaymentResponseId;
      L("LAB_RUNTIME_PROCESSING_STALE_RESPONSE_SUPPRESSED response_id=" + createdPaymentResponseId);
      auditLog("runtime_processing_stale_response_suppressed", {response_id: createdPaymentResponseId, stage: state.paymentStage || ""});
      try {
        if (vac.clearMediaBuffer) vac.clearMediaBuffer();
        if (vac.responseCancel) vac.responseCancel();
      } catch (processingAutoCancelErr) {
        L("LAB_RUNTIME_PROCESSING_STALE_RESPONSE_CANCEL_ERROR " + processingAutoCancelErr);
      }
      return;
    }
    if (state.suppressNextPaymentAutoResponse) {
      var suppressedPayload = createdPayload;
      var suppressedResponse = createdResponse;
      L("LAB_RUNTIME_PAYMENT_AUTO_RESPONSE_SUPPRESSED response_id=" + String(suppressedResponse.id || suppressedPayload.response_id || "unknown"));
      auditLog("runtime_payment_auto_response_suppressed", {response_id: String(suppressedResponse.id || suppressedPayload.response_id || "unknown"), stage: state.paymentStage || ""});
      try {
        if (vac.clearMediaBuffer) vac.clearMediaBuffer();
        if (vac.responseCancel) vac.responseCancel();
      } catch (paymentAutoCancelErr) {
        L("LAB_RUNTIME_PAYMENT_AUTO_RESPONSE_CANCEL_ERROR " + paymentAutoCancelErr);
      }
      state.responseInProgress = false;
      state.assistantAudioActive = false;
      state.suppressNextPaymentAutoResponse = false;
      maybeRunRuntimePaymentAction(vac, state, "auto_response_cancelled");
      return;
    }
    if (state.responseTimeoutTimer) { try { clearTimeout(state.responseTimeoutTimer); } catch (_) {} }
    state.responseTimeoutTimer = setTimeout(function () {
      state.responseTimeoutTimer = null;
      if (!state.responseInProgress || state.callEnded || state.transferInProgress) return;
      L("LAB_RESPONSE_TIMEOUT delay_ms=" + LAB_RESPONSE_TIMEOUT_MS);
      auditLog("response_timeout", {delay_ms: LAB_RESPONSE_TIMEOUT_MS});
      queueCallLog(state, "response_timeout", {delay_ms: LAB_RESPONSE_TIMEOUT_MS});
      try { if (vac.clearMediaBuffer) vac.clearMediaBuffer(); if (vac.responseCancel) vac.responseCancel(); } catch (_) {}
      state.responseInProgress = false;
      vac.responseCreate({response: {instructions: "Continue with one short customer-facing question or the one required tool call. Do not skip the active item's required choices or confirmation."}});
    }, LAB_RESPONSE_TIMEOUT_MS);
    var p = e && e.data && e.data.payload ? e.data.payload : {};
    var response = p.response || {};
    getResponseRecord(response.id || p.response_id || "unknown");
    var createdResponseId = String(response.id || p.response_id || "unknown");
    if (state.anythingElseMicrophaseStage === "forcing" && !state.anythingElseMicrophaseResponseId) {
      state.anythingElseMicrophaseStage = "speaking";
      state.anythingElseMicrophaseResponseId = createdResponseId;
      L("LAB_ANYTHING_ELSE_EXACT_RESPONSE response_id=" + createdResponseId + " normal_tools_preserved=true");
    }
    L("LAB_RESPONSE_CREATED response_id=" + createdResponseId);
    auditLog("response_created", {response_id: createdResponseId});
    queueCallLog(state, "response_created", {response_id: createdResponseId});
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.ResponseDone, function (e) {
    state.responseInProgress = false;
    if (state.responseTimeoutTimer) { try { clearTimeout(state.responseTimeoutTimer); } catch (_) {} state.responseTimeoutTimer = null; }
    state.lastResponseDoneAt = Date.now();
    var p = e && e.data && e.data.payload ? e.data.payload : {};
    var response = p.response || {};
    var record = getResponseRecord(response.id || p.response_id || "unknown");
    record.done = true;
    record.expectedCalls = Math.max(record.expectedCalls, countFunctionCalls(response));
    L("LAB_RESPONSE_DONE response_id=" + record.id + " expected_calls=" + record.expectedCalls + " completed_calls=" + record.completedCalls);
    var responseTranscript = responseAssistantTranscript(response);
    if (record.firstOrderingToolCallId) {
      var firstCall = record.calls[record.firstOrderingToolCallId] || {};
      var expectedAnnouncement = expectedAnnouncementForTool(record.firstOrderingToolName, firstCall.args || {});
      var announcementOk = expectedAnnouncement ? responseTranscript.toLowerCase().indexOf(expectedAnnouncement) >= 0 : true;
      L("LAB_TOOL_ANNOUNCEMENT_CHECK response_id=" + record.id + " tool=" + record.firstOrderingToolName + " ok=" + announcementOk + " expected=" + expectedAnnouncement + " transcript=" + responseTranscript);
      auditLog("tool_announcement_check", {response_id: record.id, tool: record.firstOrderingToolName, ok: announcementOk, expected: expectedAnnouncement, transcript: responseTranscript});
      queueCallLog(state, "tool_announcement_check", {response_id: record.id, tool: record.firstOrderingToolName, ok: announcementOk, expected: expectedAnnouncement, transcript: responseTranscript});
    }
    auditLog("response_done", {response_id: record.id, expected_calls: record.expectedCalls, completed_calls: record.completedCalls});
    queueCallLog(state, "response_done", {response_id: record.id, expected_calls: record.expectedCalls, completed_calls: record.completedCalls});
    if (state.anythingElseMicrophaseStage === "speaking" && record.id === state.anythingElseMicrophaseResponseId) {
      restoreMainAfterAnythingElseMicrophase(vac, state, "exact_question_response_done");
    } else if (state.anythingElseMicrophaseStage === "pending" && record.id === state.anythingElseMicrophaseSourceResponseId) {
      maybeInstallAnythingElseMicrophase(vac, state, "source_response_done");
    }
    if (state.processingAutoResponseCancelPending &&
        (!state.processingAutoResponseId || state.processingAutoResponseId === "unknown" || state.processingAutoResponseId === record.id)) {
      state.processingAutoResponseCancelPending = false;
      state.processingAutoResponseId = "";
      L("LAB_RUNTIME_PROCESSING_STALE_RESPONSE_DONE response_id=" + record.id);
      auditLog("runtime_processing_stale_response_done", {response_id: record.id});
      try { if (vac.clearMediaBuffer) vac.clearMediaBuffer(); } catch (_) {}
      maybeRunRuntimePaymentAction(vac, state, "stale_processing_response_done");
    }
    maybeContinueAfterTools("response_done");
  });

  if (Grok.Events && Grok.Events.WebSocketMediaStarted) {
    addEvent(vac, Grok.Events.WebSocketMediaStarted, function () {
      if (state.processingAutoResponseCancelPending) {
        L("LAB_RUNTIME_PROCESSING_STALE_AUDIO_BLOCKED");
        auditLog("runtime_processing_stale_audio_blocked", {});
        try {
          if (vac.clearMediaBuffer) vac.clearMediaBuffer();
          if (vac.responseCancel) vac.responseCancel();
        } catch (processingMediaCancelErr) {
          L("LAB_RUNTIME_PROCESSING_STALE_AUDIO_CANCEL_ERROR " + processingMediaCancelErr);
        }
        state.assistantAudioActive = false;
        return;
      }
      state.assistantAudioActive = true;
      L("LAB_ASSISTANT_MEDIA_STARTED");
      auditLog("assistant_media_started", {});
    });
  }

  if (Grok.Events && Grok.Events.WebSocketMediaEnded) {
    addEvent(vac, Grok.Events.WebSocketMediaEnded, function () {
      state.assistantAudioActive = false;
      L("LAB_ASSISTANT_MEDIA_ENDED");
      auditLog("assistant_media_ended", {});
      armPendingSilenceReprompt(vac, state);
      if (state.anythingElseMicrophaseStage === "pending") maybeInstallAnythingElseMicrophase(vac, state, "media_ended");
      maybeRunRuntimePaymentAction(vac, state, "media_ended");
      maybeContinueAfterTools("media_ended");
    });
  }

  addEvent(vac, Grok.VoiceAgentAPIEvents.InputAudioBufferSpeechStarted, function () {
    if (state.anythingElseMicrophaseStage === "pending") {
      state.anythingElseMicrophaseStage = "";
      state.anythingElseMicrophaseSourceResponseId = "";
      state.anythingElseMicrophaseResponseId = "";
      state.anythingElseMicrophaseExactSpoken = false;
      L("LAB_ANYTHING_ELSE_MICROPHASE_SKIPPED reason=user_spoke_before_install");
    } else if (state.anythingElseMicrophaseStage === "forcing" ||
               state.anythingElseMicrophaseStage === "speaking") {
      restoreMainAfterAnythingElseMicrophase(vac, state, "caller_speech_started_normal_session_already_active");
    }
    state.userSpeaking = true;
    state.lastUserActivityAt = Date.now();
    cancelSilenceReprompt(state, "user_speech_started");
    state.inputEpoch += 1;
    L("LAB_USER_SPEECH_STARTED epoch=" + state.inputEpoch + " cancel_response=" + state.responseInProgress + " cancel_audio=" + state.assistantAudioActive);
    auditLog("user_speech_started", {epoch: state.inputEpoch, cancel_response: state.responseInProgress, cancel_audio: state.assistantAudioActive});

    if (state.continuationTimer) {
      try { clearTimeout(state.continuationTimer); } catch (_) {}
      state.continuationTimer = null;
    }
    state.continuationScheduled = false;

    for (var i = state.responseOrder.length - 1; i >= 0; i--) {
      var pendingResponseId = state.responseOrder[i];
      var pendingRecord = state.responses[pendingResponseId];
      if (!pendingRecord || pendingRecord.continuationSent || pendingRecord.startedCalls < 1) continue;
      if (pendingRecord.inputEpoch < state.inputEpoch) {
        pendingRecord.supersededByUser = true;
        pendingRecord.suppressContinuation = true;
        state.responseOrder.splice(i, 1);
        L("LAB_PENDING_TOOL_CONTINUATION_REMOVED response_id=" + pendingRecord.id + " old_epoch=" + pendingRecord.inputEpoch + " new_epoch=" + state.inputEpoch);
      }
    }

    try {
      if (vac.clearMediaBuffer) vac.clearMediaBuffer();
      if (vac.responseCancel && (state.responseInProgress || state.assistantAudioActive)) vac.responseCancel();
    } catch (e) {
      L("LAB_BARGE_CANCEL_ERROR " + e);
    }
    state.responseInProgress = false;
    state.assistantAudioActive = false;
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.ConversationItemInputAudioTranscriptionCompleted, function (e) {
    var p = e && e.data && e.data.payload ? e.data.payload : {};
    state.userSpeaking = false;
    state.userTurnSerial += 1;
    state.latestUserTranscript = String(p.transcript || "");
    state.lastUserActivityAt = Date.now();
    logChunks("LAB_USER_TRANSCRIPT", state.latestUserTranscript);
    auditLog("user_transcript", {turn: state.userTurnSerial, epoch: state.inputEpoch, transcript: state.latestUserTranscript});
    queueCallLog(state, "transcript_turn", {sequence_number: state.userTurnSerial, role: "user", speaker: "user", text: state.latestUserTranscript});
    if (commitRuntimePaymentField(vac, state, state.latestUserTranscript)) {
      L("LAB_RUNTIME_PAYMENT_FIELD_COMMIT stage=" + state.paymentStage + " turn=" + state.userTurnSerial);
      return;
    }
    L("LAB_AGENT_LANGUAGE_DECISION turn=" + state.userTurnSerial + " runtime_override=false previous_question=" + String(state.lastAssistantTranscript || "").substring(0, 120));
    auditLog("agent_language_decision", {turn: state.userTurnSerial, runtime_override: false, previous_assistant: state.lastAssistantTranscript || "", transcript: state.latestUserTranscript});
    L("LAB_USER_TURN_COMMITTED turn=" + state.userTurnSerial + " epoch=" + state.inputEpoch);
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.ResponseOutputAudioTranscriptDone, function (e) {
    var p = e && e.data && e.data.payload ? e.data.payload : {};
    var assistantTranscript = String(p.transcript || "");
    if (state.anythingElseMicrophaseStage === "speaking" &&
        String(p.response_id || "") === state.anythingElseMicrophaseResponseId &&
        assistantTranscript.trim() === "Anything else for the order?") {
      state.anythingElseMicrophaseExactSpoken = true;
      L("LAB_ANYTHING_ELSE_MICROPHASE_EXACT");
      auditLog("anything_else_microphase_exact", {});
      queueCallLog(state, "anything_else_microphase_exact", {});
      restoreMainAfterAnythingElseMicrophase(vac, state, "exact_question_transcript_done");
    }
    state.lastAssistantTranscript = assistantTranscript;
    logChunks("LAB_ASSISTANT_TRANSCRIPT", assistantTranscript);
    auditLog("assistant_transcript", {item_id: p.item_id || "", transcript: assistantTranscript});
    queueCallLog(state, "transcript_turn", {role: "assistant", speaker: "assistant", text: assistantTranscript, metadata: {item_id: p.item_id || ""}});
    if (/Is everything correct\?\s*$/i.test(assistantTranscript)) {
      restoreMainSession(vac, state, "final_readback_agent_decision");
      L("LAB_FINAL_APPROVAL_AGENT_OWNS_DECISION threshold=0.5 silence_duration_ms=650 tools=ALL_NORMAL_TOOLS");
      auditLog("final_approval_agent_decision", {threshold: 0.5, silence_duration_ms: 650, tools: "ALL_NORMAL_TOOLS"});
    } else if (assistantTranscript.trim() === paymentQuestionText()) {
      state.awaitingPaymentChoice = false;
      state.paymentChoice = "";
      state.pendingForcedCardPrompt = false;
      L("LAB_PAYMENT_CHOICE_AGENT_OWNS_DECISION tools=ALL_NORMAL_TOOLS");
      auditLog("payment_choice_agent_decision", {tools: "ALL_NORMAL_TOOLS"});
    } else if (assistantTranscript.trim() === cardNumberPromptText()) {
      auditLog("card_prompt_exact", {payment_stage: state.paymentStage || ""});
      queueCallLog(state, "card_prompt_exact", {payment_stage: state.paymentStage || ""});
      if (!state.paymentDtmfMode || state.paymentStage !== "card_number") beginCardCapture(vac, state, "card_prompt_spoken_fallback");
    }
    var isSilenceForceEcho = state.lastSilenceForceText && Date.now() < state.suppressSilenceRearmUntil && assistantTranscript.trim() === state.lastSilenceForceText.trim();
    if (isSilenceForceEcho) {
      state.lastSilenceForceText = "";
    } else if (transcriptLooksLikeQuestion(assistantTranscript)) {
      scheduleSilenceAfterQuestion(state, assistantTranscript);
    }
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.Error, function (e) {
    var p = e && e.data && e.data.payload ? e.data.payload : e;
    logChunks("LAB_GROK_ERROR", p || {});
    auditLog("grok_error", p || {});
    queueCallLog(state, "grok_error", p || {});
  });

  addEvent(vac, Grok.VoiceAgentAPIEvents.ResponseFunctionCallArgumentsDone, async function (e) {
    var p = e && e.data && e.data.payload ? e.data.payload : {};
    var name = String(p.name || "");
    var callId = String(p.call_id || "");
    var responseId = String(p.response_id || "unknown");
    var args = parseArgs(p.arguments);
    var record = getResponseRecord(responseId);
    var toolEpoch = record.inputEpoch;
    var toolUserTurn = record.userTurnSerial;

    if (!record.calls[callId]) {
      var toolStartedAtMs = Date.now();
      record.calls[callId] = {
        done: false,
        name: name,
        args: safeClone(args),
        startedAtMs: toolStartedAtMs,
        startedAtIso: new Date(toolStartedAtMs).toISOString()
      };
      record.startedCalls += 1;
      record.expectedCalls = Math.max(record.expectedCalls, record.startedCalls);
    }

    state.lastToolActivityAt = Date.now();
    cancelSilenceReprompt(state, "tool_call");
    if (state.paymentStage && (name === "get_ordering_catalog" || name === "get_coupon_plan" || name === "compile_and_price_order" || name === "ask_anything_else")) {
      restoreMainSession(vac, state, "agent_returned_to_ordering_tool_" + name);
    }
    logChunks("LAB_TOOL_CALL", {name: name, call_id: callId, response_id: responseId, args: args});
    auditLog("tool_call", {name: name, call_id: callId, response_id: responseId, args: args});

    var blockedByOneToolContract = false;
    if (isOrderingTool(name)) {
      if (!record.firstOrderingToolCallId) {
        record.firstOrderingToolCallId = callId;
        record.firstOrderingToolName = name;
      } else if (record.firstOrderingToolCallId !== callId) {
        blockedByOneToolContract = true;
        record.orderingToolViolationCount += 1;
        L("LAB_ONE_ORDERING_TOOL_BLOCKED response_id=" + responseId + " allowed=" + record.firstOrderingToolName + " blocked=" + name);
        auditLog("one_ordering_tool_violation", {response_id: responseId, allowed_tool: record.firstOrderingToolName, blocked_tool: name});
        queueCallLog(state, "one_ordering_tool_violation", {response_id: responseId, allowed_tool: record.firstOrderingToolName, blocked_tool: name});
      }
    }

    var rawOutput;
    try {
      if (blockedByOneToolContract) {
        rawOutput = {
          ok: false,
          tool: name,
          error_code: "ONE_ORDERING_TOOL_PER_RESPONSE",
          blocked: true,
          allowed_tool: record.firstOrderingToolName,
          next_step: "Finish the current active item using the first tool result. Do not start another item or coupon until the current item is complete, read back, and confirmed."
        };
      } else if (name === "ask_anything_else") {
        record.suppressContinuation = true;
        state.anythingElseMicrophaseStage = "pending";
        state.anythingElseMicrophaseSourceResponseId = responseId;
        state.anythingElseMicrophaseResponseId = "";
        state.anythingElseMicrophaseExactSpoken = false;
        rawOutput = {
          ok: true,
          tool: "ask_anything_else",
          exact_question_pending: true,
          normal_session_and_tools_preserved: true,
          next_step: "Runtime will force the exact question. Produce no additional response. You will interpret the caller answer in the normal session."
        };
        L("LAB_ANYTHING_ELSE_EXACT_REQUESTED response_id=" + responseId + " normal_tools_preserved=true");
        auditLog("anything_else_exact_requested", {response_id: responseId, normal_tools_preserved: true});
        queueCallLog(state, "anything_else_exact_requested", {response_id: responseId, normal_tools_preserved: true});
      } else if (name === "get_ordering_catalog") {
        var menuPayload = {
          store_number: LAB_STORE_NUMBER,
          order_type: LAB_ORDER_TYPE,
          category: String(args.category || "")
        };
        var requestedItemQuery = String(args.item_query || "").trim();
        if (menuPayload.category === "pizza" && isPizzaBurgerQuery(requestedItemQuery)) {
          menuPayload.category = "subs";
          requestedItemQuery = "";
          L("LAB_MENU_ROUTE_NORMALIZED item=Pizza Burger from=pizza to=subs first_lookup=full_category");
          auditLog("menu_route_normalized", {item: "Pizza Burger", from_category: "pizza", to_category: "subs", first_lookup: "full_category"});
          queueCallLog(state, "menu_route_normalized", {item: "Pizza Burger", from_category: "pizza", to_category: "subs", first_lookup: "full_category"});
        }
        if (requestedItemQuery && menuPayload.category !== "beverages") menuPayload.item_query = requestedItemQuery;
        rawOutput = await postJson(LAB_BASE_URL + "/grok-tool/get-ordering-catalog", menuPayload);
        if (menuPayload.category === "pizza" && menuPayload.item_query) {
          rawOutput = enrichPizzaSpecialtyLookup(rawOutput, menuPayload.item_query);
        }
      } else if (name === "get_coupon_plan") {
        var couponNumber = args.coupon_number !== undefined && args.coupon_number !== null && String(args.coupon_number).trim() !== ""
          ? Number(args.coupon_number)
          : null;
        var completedCouponNumber = toolUserTurn === state.userTurnSerial
          ? completedCouponNumberFromTranscript(state.latestUserTranscript)
          : null;
        if (completedCouponNumber && isFinite(completedCouponNumber.number) && completedCouponNumber.number !== couponNumber) {
          var originalCouponNumber = couponNumber;
          couponNumber = completedCouponNumber.number;
          L("LAB_COUPON_NUMBER_NORMALIZED from=" + String(originalCouponNumber) + " to=" + String(couponNumber) + " transcript=" + state.latestUserTranscript);
          auditLog("coupon_number_normalized", {from: originalCouponNumber, to: couponNumber, transcript: state.latestUserTranscript, user_turn: toolUserTurn});
          queueCallLog(state, "coupon_number_normalized", {from: originalCouponNumber, to: couponNumber, transcript: state.latestUserTranscript, user_turn: toolUserTurn});
        }
        var couponQuery = String(args.query || "").trim();
        var couponPayload = {
          store_number: LAB_STORE_NUMBER,
          order_type: LAB_ORDER_TYPE
        };
        if (couponNumber !== null && isFinite(couponNumber)) couponPayload.coupon_number = couponNumber;
        if (couponQuery) couponPayload.query = couponQuery;
        rawOutput = await postJson(LAB_BASE_URL + "/grok-tool/get-coupon-plan", couponPayload);
        rawOutput = addCouponSpeechFields(rawOutput);
        if (rawOutput && rawOutput.ok === true) {
          rawOutput = enrichCoupon999Plan(rawOutput);
          var returnedPlans = Array.isArray(rawOutput.coupon_plans) ? rawOutput.coupon_plans : [];
          for (var cp = 0; cp < returnedPlans.length; cp++) {
            var returnedNumber = Number(returnedPlans[cp] && returnedPlans[cp].coupon_number);
            if (!isFinite(returnedNumber)) continue;
            state.couponPlansByNumber[String(returnedNumber)] = safeClone({
              ok: true,
              coupon_number: returnedNumber,
              coupon_plans: [returnedPlans[cp]]
            });
            L("LAB_COUPON_PLAN_STORED coupon_number=" + String(returnedNumber));
          }
        }
      } else if (name === "compile_and_price_order") {
        var compilePayload = buildCompilePayloadFromSession(args, state);
        var compileSessionInfo = sessionInfoForBackend(state);
        L("LAB_COMPILE_SESSION_INJECTED store_number=" + String(compileSessionInfo.store_number) + " order_type=" + String(compileSessionInfo.order_type) + " phone_present=" + Boolean(compileSessionInfo.phone) + " customer_name_present=" + Boolean(compileSessionInfo.customer_name) + " delivery=" + Boolean(compileSessionInfo.delivery) + " curbside=" + Boolean(compileSessionInfo.curbside));
        auditLog("compile_session_injected", {store_number: compileSessionInfo.store_number, order_type: compileSessionInfo.order_type, phone_present: Boolean(compileSessionInfo.phone), customer_name_present: Boolean(compileSessionInfo.customer_name), delivery: Boolean(compileSessionInfo.delivery), curbside: Boolean(compileSessionInfo.curbside)});

        var coupon999Validation = validateCoupon999CompilePayload(compilePayload);
        if (coupon999Validation) {
          rawOutput = coupon999Validation;
          logChunks("LAB_COUPON_999_VALIDATION", rawOutput);
        } else {
          rawOutput = await postJson(LAB_BASE_URL + "/grok-tool/compile-and-price-order", compilePayload);
        }

        if (toolEpoch !== state.inputEpoch) {
          rawOutput = {
            ok: false,
            tool: "compile_and_price_order",
            stage: "cancelled",
            cancelled: true,
            superseded_by_new_user_input: true,
            next_step: "Ignore this stale result. Apply the caller's newest instruction to the complete cart before compiling again."
          };
          record.supersededByUser = true;
          L("LAB_STALE_COMPILE_RESULT_DISCARDED response_id=" + responseId + " tool_epoch=" + toolEpoch + " current_epoch=" + state.inputEpoch);
        } else if (rawOutput && rawOutput.ok === true && rawOutput.order_json) {
          state.lastPricedOrderJson = safeClone(rawOutput.order_json);
          state.lastPricedTotal = rawOutput.grand_total;
          state.lastPricedItems = safeClone(compilePayload.items || []);
          state.lastPricedCouponNumbers = Array.isArray(compilePayload.coupon_numbers)
            ? safeClone(compilePayload.coupon_numbers)
            : (compilePayload.coupon_number !== undefined ? [compilePayload.coupon_number] : []);
          if (state.submissionStatus !== "SUBMITTED_LOCKED" && state.submissionStatus !== "SUBMITTING" && state.submissionStatus !== "SUBMISSION_UNKNOWN") {
            state.submissionStatus = "READY";
            state.submissionLastError = "";
          }
          rawOutput.priced_items = safeClone(state.lastPricedItems);
          rawOutput.priced_coupon_numbers = safeClone(state.lastPricedCouponNumbers);
          rawOutput.priced_coupons = buildPricedCoupons(state.lastPricedCouponNumbers, state.lastPricedItems, state.couponPlansByNumber);
          rawOutput.pickup_location_for_readback = buildPickupLocationForReadback(rawOutput);
          rawOutput.grand_total_for_speech = formatCurrencyForSpeech(rawOutput.grand_total);
          rawOutput.final_readback_required = Boolean(rawOutput.pickup_location_for_readback);
          rawOutput.final_readback_rule = "Begin with the first priced item. Do not repeat Compiling and pricing that now. Read every priced item and coupon choice without individual prices. Speak every coupon number as separate digits using coupon_spoken_label. Then read the pickup store name, address, and landmark, then only grand_total_for_speech, and ask Is everything correct? Do not say California or C A.";
          rawOutput.spoken_price_policy = "Grand total only unless the caller specifically asks for an individual price.";
          if (!rawOutput.final_readback_required) {
            rawOutput.ok = false;
            rawOutput.error_code = "PICKUP_LOCATION_REQUIRED_FOR_FINAL_READBACK";
            rawOutput.error = "Pickup store name, address, and landmark are missing.";
            state.lastPricedOrderJson = null;
            state.lastPricedTotal = null;
          }
          L("LAB_PRICED_ORDER_STORED privately=true grand_total=" + String(rawOutput.grand_total) + " priced_items=" + state.lastPricedItems.length + " priced_coupons=" + rawOutput.priced_coupons.length + " pickup_location=" + rawOutput.pickup_location_for_readback);
          auditLog("priced_order_stored", {grand_total: rawOutput.grand_total, priced_item_count: state.lastPricedItems.length, priced_coupon_count: rawOutput.priced_coupons.length, pickup_location: rawOutput.pickup_location_for_readback});
          queueCallLog(state, "order_snapshot", {reason: "after_compile_and_price", grand_total: rawOutput.grand_total, customer_facing_items: state.lastPricedItems, coupon_numbers: state.lastPricedCouponNumbers});
        } else {
          state.lastPricedOrderJson = null;
          state.lastPricedTotal = null;
          state.lastPricedItems = [];
          state.lastPricedCouponNumbers = [];
          if (state.submissionStatus !== "SUBMITTED_LOCKED" && state.submissionStatus !== "SUBMITTING" && state.submissionStatus !== "SUBMISSION_UNKNOWN") state.submissionStatus = "";
          L("LAB_PRICED_ORDER_CLEARED compile_ok=false first_missing_question=" + String(rawOutput && rawOutput.first_missing_question ? rawOutput.first_missing_question : ""));
        }
      } else if (name === "get_payment_token") {
        state.paymentChoice = "card";
        if (!state.paymentBillingZip && digitsOnly(state.paymentZipDigits).length === 5) state.paymentBillingZip = digitsOnly(state.paymentZipDigits).slice(0, 5);
        if (!state.lastPricedOrderJson) {
          rawOutput = {ok: false, error: "No priced order is available for payment."};
        } else if (!acceptedPaymentCardNumber(state.paymentCardAccount)) {
          rawOutput = {ok: false, error: "Runtime keypad card number is missing or invalid."};
        } else if (!validExpiration(state.paymentCardExpdate)) {
          rawOutput = {ok: false, error: "Runtime keypad expiration is missing or invalid."};
        } else if (digitsOnly(state.paymentBillingZip || state.paymentZipDigits).length !== 5) {
          state.paymentBillingZip = digitsOnly(state.paymentZipDigits).slice(0, 5);
          rawOutput = {ok: false, error: "Runtime keypad billing ZIP is missing or invalid."};
        } else {
          var tokenPayload = {
            store_number: LAB_STORE_NUMBER,
            type_code: paymentTypeCodeFromCardNumber(state.paymentCardAccount),
            account: state.paymentCardAccount,
            expdate: state.paymentCardExpdate,
            telno: callerPhone,
            name: "Lean Ordering Lab",
            street: LAB_PICKUP_ADDRESS,
            zip: state.paymentBillingZip
          };
          auditLog("payment_token_request", {card_digits_len: state.paymentCardAccount.length, expdate_len: state.paymentCardExpdate.length, zip_len: state.paymentBillingZip.length, type_code: tokenPayload.type_code});
          rawOutput = await postJson(LAB_BASE_URL + "/tool/get-payment-token", tokenPayload);
          state.paymentInfo = paymentInfoFromToken(rawOutput, state);
          if (state.paymentInfo && state.paymentInfo.token) {
            rawOutput.payment_token_saved = true;
            installPaymentStage(vac, state, "token_success", "token_saved");
            record.continuationInstructions = 'Say exactly: "Submitting that now." Then call submit_order with payment_method card. Say nothing else.';
            state.paymentDtmfMode = false;
            state.paymentDtmfDigits = "";
            state.paymentExpDigits = "";
            state.paymentZipDigits = "";
            state.paymentCardAccount = "";
          } else {
            rawOutput.ok = false;
            rawOutput.error = rawOutput.error || "Payment tokenization returned no usable token.";
          }
        }
      } else if (name === "submit_order") {
        var requestedPaymentMethod = String(args.payment_method || "").toLowerCase();
        if (requestedPaymentMethod !== "card" && requestedPaymentMethod !== "pay_at_store") {
          requestedPaymentMethod = state.paymentInfo && state.paymentInfo.token ? "card" : "pay_at_store";
          L("LAB_SUBMIT_PAYMENT_METHOD_FALLBACK method=" + requestedPaymentMethod);
          auditLog("submit_payment_method_fallback", {method: requestedPaymentMethod});
        }
        if (state.submissionStatus === "SUBMITTED_LOCKED" || state.submitted) {
          state.submissionStatus = "SUBMITTED_LOCKED";
          rawOutput = {ok: false, submitted: false, submission_status: "SUBMITTED_LOCKED", error_code: "ORDER_ALREADY_SUBMITTED", error: "This order was already submitted and is permanently locked. Transfer any modification or payment request to staff."};
          installSubmissionTerminalSession(vac, state, "SUBMITTED_LOCKED", "duplicate_submit_blocked");
        } else if (state.submissionStatus === "SUBMITTING") {
          rawOutput = {ok: false, submitted: false, submission_status: "SUBMITTING", error_code: "SUBMISSION_IN_PROGRESS", error: "The order submission is already in progress. Do not call submit_order again."};
        } else if (state.submissionStatus === "SUBMISSION_UNKNOWN") {
          rawOutput = {ok: false, submitted: false, submission_status: "SUBMISSION_UNKNOWN", error_code: "SUBMISSION_RESULT_UNKNOWN", error: "The prior submission result is unknown. Do not retry; transfer to staff."};
          installSubmissionTerminalSession(vac, state, "SUBMISSION_UNKNOWN", "repeat_submit_blocked_unknown_result");
        } else if (!state.lastPricedOrderJson || (state.submissionStatus !== "READY" && state.submissionStatus !== "RETRYABLE")) {
          rawOutput = {ok: false, submitted: false, submission_status: state.submissionStatus, error_code: "PRICED_ORDER_REQUIRED", error: "No current successfully priced order is available. Compile and price the complete current order first."};
        } else if (requestedPaymentMethod === "card" && !(state.paymentInfo && state.paymentInfo.token)) {
          rawOutput = {ok: false, submitted: false, submission_status: state.submissionStatus, error_code: "PAYMENT_TOKEN_REQUIRED", error: "Card payment has not been tokenized successfully."};
        } else {
          if (requestedPaymentMethod === "pay_at_store") {
            switchPaymentToPayAtStore(vac, state, "agent_submit_tool_selected_pay_at_store", false);
          } else {
            state.paymentChoice = "card";
          }
          state.submissionStatus = "SUBMITTING";
          state.submissionAttemptSerial += 1;
          state.submissionLastError = "";
          var attemptNumber = state.submissionAttemptSerial;
          L("LAB_SUBMISSION_LOCK status=SUBMITTING attempt=" + attemptNumber + " payment_method=" + requestedPaymentMethod);
          auditLog("submission_lock", {status: "SUBMITTING", attempt: attemptNumber, payment_method: requestedPaymentMethod});
          queueCallLog(state, "submission_lock", {status: "SUBMITTING", attempt: attemptNumber, payment_method: requestedPaymentMethod});
          var submitOrderJson = safeClone(state.lastPricedOrderJson);
          submitOrderJson.empno = LAB_EMPLOYEE_NUMBER;
          if (requestedPaymentMethod === "card" && state.paymentInfo && state.paymentInfo.token) {
            submitOrderJson.payment = safeClone(state.paymentInfo);
          } else if (submitOrderJson.payment) {
            delete submitOrderJson.payment;
          }
          try {
            rawOutput = await postJson(LAB_BASE_URL + "/tool/submit-order", {
              order_json: JSON.stringify(submitOrderJson)
            });
            if (submissionHasOrderEvidence(rawOutput)) {
              state.submissionStatus = "SUBMITTED_LOCKED";
              state.submitted = true;
              rawOutput.submission_status = "SUBMITTED_LOCKED";
              var submittedOrderNumber = String(rawOutput.customer_facing_order_number || rawOutput.order_number || "");
              var submittedPickupEstimate = String(rawOutput.pickup_estimate || rawOutput.quote_text || rawOutput.quote || rawOutput.quoted || "");
              record.continuationInstructions = buildPostSubmitInstructions(submittedOrderNumber, submittedPickupEstimate);
              installSubmissionTerminalSession(vac, state, "SUBMITTED_LOCKED", "confirmed_order_created");
              L("LAB_ORDER_SUBMITTED_LOCKED order_number=" + submittedOrderNumber + " attempt=" + attemptNumber);
              auditLog("order_submitted", {order_number: submittedOrderNumber, pickup_estimate: submittedPickupEstimate, submission_status: state.submissionStatus, attempt: attemptNumber});
              queueCallLog(state, "order_submitted", {order_number: submittedOrderNumber, pickup_estimate: submittedPickupEstimate, submission_status: state.submissionStatus, attempt: attemptNumber});
            } else if (submissionFailureIsConfirmed(rawOutput)) {
              state.submissionStatus = "RETRYABLE";
              state.submitted = false;
              state.submissionLastError = String(rawOutput.error || rawOutput.message || "Submission failed.");
              rawOutput.submission_status = "RETRYABLE";
              rawOutput.retry_allowed = true;
              if (requestedPaymentMethod === "card") state.paymentInfo = null;
              L("LAB_SUBMISSION_UNLOCK status=RETRYABLE attempt=" + attemptNumber + " error=" + state.submissionLastError);
              auditLog("submission_unlock", {status: "RETRYABLE", attempt: attemptNumber, error: state.submissionLastError});
              queueCallLog(state, "submission_unlock", {status: "RETRYABLE", attempt: attemptNumber, error: state.submissionLastError});
            } else {
              state.submissionStatus = "SUBMISSION_UNKNOWN";
              state.submitted = false;
              rawOutput = {ok: false, submitted: false, submission_unknown: true, submission_status: "SUBMISSION_UNKNOWN", error_code: "SUBMISSION_RESULT_UNKNOWN", error: "The submission result could not be verified. Do not retry; transfer to staff."};
              installSubmissionTerminalSession(vac, state, "SUBMISSION_UNKNOWN", "backend_response_not_authoritative");
            }
          } catch (submitError) {
            var classifiedSubmit = classifySubmitException(submitError);
            rawOutput = classifiedSubmit.output || {};
            state.submissionStatus = classifiedSubmit.status;
            rawOutput.submission_status = classifiedSubmit.status;
            if (classifiedSubmit.status === "SUBMITTED_LOCKED") {
              state.submitted = true;
              var caughtOrderNumber = String(rawOutput.customer_facing_order_number || rawOutput.order_number || "");
              var caughtEstimate = String(rawOutput.pickup_estimate || rawOutput.quote_text || rawOutput.quote || rawOutput.quoted || "");
              record.continuationInstructions = buildPostSubmitInstructions(caughtOrderNumber, caughtEstimate);
              installSubmissionTerminalSession(vac, state, "SUBMITTED_LOCKED", "error_response_contains_order_evidence");
            } else if (classifiedSubmit.status === "RETRYABLE") {
              state.submitted = false;
              state.submissionLastError = String(rawOutput.error || rawOutput.message || submitError.message || "Submission failed.");
              rawOutput.retry_allowed = true;
              if (requestedPaymentMethod === "card") state.paymentInfo = null;
              L("LAB_SUBMISSION_UNLOCK status=RETRYABLE attempt=" + attemptNumber + " error=" + state.submissionLastError);
              auditLog("submission_unlock", {status: "RETRYABLE", attempt: attemptNumber, error: state.submissionLastError});
              queueCallLog(state, "submission_unlock", {status: "RETRYABLE", attempt: attemptNumber, error: state.submissionLastError});
            } else {
              state.submitted = false;
              installSubmissionTerminalSession(vac, state, "SUBMISSION_UNKNOWN", "submit_exception_without_confirmed_failure");
            }
          }
        }
      } else if (name === "transfer_call") {
        var terminalSubmissionTransfer = state.submissionStatus === "SUBMITTED_LOCKED" || state.submissionStatus === "SUBMISSION_UNKNOWN";
        if (!terminalSubmissionTransfer && !transferConsentSatisfied(state)) {
          rawOutput = {
            ok: false,
            tool: "transfer_call",
            transferred: false,
            error_code: "TRANSFER_CONFIRMATION_REQUIRED",
            error: "The caller did not explicitly request a transfer and has not approved the transfer offer.",
            next_step: "Ask exactly: Would you like me to transfer you to a member of our team? Then stop and wait for a clear yes. Do not call transfer_call in this response."
          };
          L("LAB_TRANSFER_CONFIRMATION_REQUIRED transcript=" + String(state.latestUserTranscript || "").substring(0, 120));
          auditLog("transfer_confirmation_required", {transcript: state.latestUserTranscript || "", previous_assistant: state.lastAssistantTranscript || ""});
          queueCallLog(state, "transfer_confirmation_required", {transcript: state.latestUserTranscript || "", previous_assistant: state.lastAssistantTranscript || ""});
        } else {
          rawOutput = startSipReferTransfer(call, state, args);
        }
      } else {
        rawOutput = {ok: false, error: "Unknown lab tool: " + name};
      }

      if (name !== "compile_and_price_order" && name !== "submit_order" && toolEpoch !== state.inputEpoch) {
        rawOutput = {
          ok: false,
          cancelled: true,
          superseded_by_new_user_input: true,
          next_step: "Ignore this stale tool result and follow the caller's newest instruction."
        };
        record.supersededByUser = true;
        L("LAB_STALE_TOOL_RESULT_DISCARDED name=" + name + " response_id=" + responseId + " tool_epoch=" + toolEpoch + " current_epoch=" + state.inputEpoch);
      }

      if (name === "get_payment_token" && !state.paymentBillingZip && digitsOnly(state.paymentZipDigits).length === 5) {
        state.paymentBillingZip = digitsOnly(state.paymentZipDigits).slice(0, 5);
      }
      var modelOutput = sanitizeToolOutputForModel(name, rawOutput);
      if (name === "compile_and_price_order" && modelOutput && modelOutput.ok === true && modelOutput.final_readback_required === true) {
        record.continuationInstructions = buildFinalReadbackInstructions(modelOutput);
        logChunks("LAB_FINAL_READBACK_INSTRUCTIONS", record.continuationInstructions);
      }
      logChunks("LAB_TOOL_OUTPUT_TO_MODEL", {name: name, call_id: callId, response_id: responseId, output: modelOutput});
      auditLog("tool_result", {name: name, call_id: callId, response_id: responseId, output: modelOutput});
      queueCompletedToolCallLog(
        state,
        name,
        callId,
        args,
        modelOutput,
        record.calls[callId] && record.calls[callId].startedAtMs,
        record.calls[callId] && record.calls[callId].startedAtIso
      );
      toolOutput(vac, callId, modelOutput);
    } catch (toolError) {
      var failure = {ok: false, tool: name, error: String(toolError && toolError.message ? toolError.message : toolError)};
      if (name === "compile_and_price_order") {
        state.lastPricedOrderJson = null;
        state.lastPricedTotal = null;
        state.lastPricedItems = [];
        state.lastPricedCouponNumbers = [];
        if (state.submissionStatus !== "SUBMITTED_LOCKED" && state.submissionStatus !== "SUBMITTING" && state.submissionStatus !== "SUBMISSION_UNKNOWN") state.submissionStatus = "";
      }
      logChunks("LAB_TOOL_FAILURE", failure);
      auditLog("tool_failure", failure);
      queueCompletedToolCallLog(
        state,
        name,
        callId,
        args,
        failure,
        record.calls[callId] && record.calls[callId].startedAtMs,
        record.calls[callId] && record.calls[callId].startedAtIso
      );
      toolOutput(vac, callId, failure);
    }

    if (!record.calls[callId].done) {
      record.calls[callId].done = true;
      record.completedCalls += 1;
    }
    L("LAB_TOOL_OUTPUT_RECORDED response_id=" + responseId + " completed=" + record.completedCalls + "/" + record.expectedCalls);
    if (name === "ask_anything_else") {
      maybeInstallAnythingElseMicrophase(vac, state, "tool_output_ready");
    } else {
      maybeContinueAfterTools("tool_output_ready");
    }

    // Fallback for connectors that do not emit media-ended after a silent tool-call response.
    setTimeout(function () {
      if (state.callEnded) return;
      if (state.responseInProgress && Date.now() - state.lastResponseDoneAt > 1800) {
        state.responseInProgress = false;
        L("LAB_TOOL_CONTINUATION_STALE_RESPONSE_CLEARED");
      }
      if (state.assistantAudioActive && Date.now() - state.lastResponseDoneAt > 5000) {
        state.assistantAudioActive = false;
        L("LAB_TOOL_CONTINUATION_STALE_AUDIO_CLEARED");
      }
      if (!state.userSpeaking) maybeContinueAfterTools("fallback_timer");
    }, 2200);
  });


  try {
    if (typeof CallEvents.TransferComplete !== "undefined") {
      call.addEventListener(CallEvents.TransferComplete, function () {
        state.transferInProgress = false;
        L("LAB_SIP_REFER_COMPLETE target=" + state.transferTarget);
        auditLog("transfer_complete", {target: state.transferTarget});
        queueCallLog(state, "transfer_complete", {transfer_target: state.transferTarget});
      });
    }
    if (typeof CallEvents.TransferFailed !== "undefined") {
      call.addEventListener(CallEvents.TransferFailed, function (e) {
        state.transferInProgress = false;
        L("LAB_SIP_REFER_FAILED " + JSON.stringify(e || {}));
        auditLog("transfer_failed", {event: e || {}, target: state.transferTarget});
        queueCallLog(state, "transfer_failed", {event: e || {}, transfer_target: state.transferTarget});
      });
    }
  } catch (transferListenerError) {
    L("LAB_TRANSFER_LISTENER_ERROR " + transferListenerError);
  }

  call.addEventListener(CallEvents.Disconnected, function () {
    state.callEnded = true;
    cancelSilenceReprompt(state, "call_disconnected");
    var durationMs = Date.now() - state.callStartedAt;
    L("LAB_CALL_DISCONNECTED submitted=" + state.submitted + " duration_ms=" + durationMs);
    auditLog("call_ended", {submitted: state.submitted, submission_status: state.submissionStatus, duration_ms: durationMs, payment_choice: state.paymentChoice || ""});
    queueCallLog(state, "call_ended", {submitted: state.submitted, submission_status: state.submissionStatus, duration_ms: durationMs, payment_choice: state.paymentChoice || "", final_outcome: state.submitted ? "submitted" : (state.transferInProgress ? "transferred" : "not_submitted")});
    flushCallLogs(state, true, "disconnect_final");
    setTimeout(function () { VoxEngine.terminate(); }, 1200);
  });

  call.addEventListener(CallEvents.Failed, function (e) {
    state.callEnded = true;
    cancelSilenceReprompt(state, "call_failed");
    L("LAB_CALL_FAILED " + JSON.stringify(e || {}));
    auditLog("call_failed", {event: e || {}});
    queueCallLog(state, "call_failed", {event: e || {}});
    flushCallLogs(state, true, "failed_final");
    setTimeout(function () { VoxEngine.terminate(); }, 1200);
  });
});
