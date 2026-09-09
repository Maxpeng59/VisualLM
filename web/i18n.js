(function () {
  "use strict";

  const STORAGE_KEY = "visuallm-language";
  const SUPPORTED = ["en", "zh", "es", "hi", "fr", "de"];
  const LANGUAGE_NAMES = {
    en: "English",
    zh: "中文",
    es: "Español",
    hi: "हिन्दी",
    fr: "Français",
    de: "Deutsch",
  };

  const MESSAGES = {
    en: {
      language: "Language", app_subtitle: "Animated STEM studio",
      explanation: "Explanation", examples_playback: "Examples & Playback", resources: "Resources",
      concept: "Concept", scene: "Scene", equation_rule: "Equation / rule", waiting: "Waiting…", auto: "Auto",
      what_seeing: "What you're seeing",
      browser_intro: "Browser edition — runs entirely in your browser, no server. Enter a chemical formula, reaction, or curriculum topic, then press Visualize.",
      server_intro: "Enter any STEM idea, then press Visualize. The AI will create a custom animation and explain it here.",
      learning_checkpoints: "Learning checkpoints",
      observe_default: "Observe the motion first and identify what changes.",
      adjust_default: "Adjust a value and predict the result before replaying.",
      explain_default: "Explain the pattern in your own words to check understanding.",
      playback: "Playback", pause: "Pause", play: "Play", speed: "Speed", try_example: "Try an example",
      study_packs: "Study Packs", import_pack: "Import a pack", all_packs: "← All packs",
      start_lesson: "Start a lesson", question_heading: "What do you want to understand?",
      prompt_help: "Enter a formula, reaction, topic, or worked problem.",
      describe: "Describe", describe_help: "the idea you want to explore.",
      observe: "Observe", observe_help: "the animation and change its values.",
      question: "Question", question_help: "the result using the learning coach.",
      prompt: "Prompt", prefer: "Prefer", visualize: "Visualize", surprise: "Surprise me",
      tip: "Tip: change one variable at a time. Press Cmd/Ctrl + Enter to run.",
      reflect_practise: "Reflect and practise", learning_coach: "Learning coach",
      browser_coach_desc: "Ask for a hint, a comparison, or a next-step question. Full AI tutoring runs in the desktop app.",
      server_coach_desc: "Ask for a hint, a comparison, or a next-step question grounded in the current scene.",
      ask_tutor: "Ask the tutor", browser_placeholder: "Try a formula, reaction, or topic above, then ask about the result.",
      server_placeholder: "Ask why the curve bends, what each force means, or how to solve a similar problem.",
      browser_chat_hint: "Browser edition: lesson guidance works offline.",
      server_chat_hint: "The coach uses the current visualization as context.",
      ask: "Ask", quick_questions: "Quick questions", checking: "Checking…", detecting: "Detecting…",
      idle_formula: "Idle — enter a formula, reaction, or topic.", idle_prompt: "Idle — enter a prompt to begin.",
      orbit_hint: "drag to orbit · scroll to zoom · double-click to reset",
      browser_edition: "Browser edition", browser_features: "Chemistry · interactive demos · step-by-step solver · runs in your browser",
      code_only: "Code-only", server_offline: "Server offline", online: "online", generator: "Generator",
      no_equation: "No single equation — concept scene", adjust_values: "Adjust the values — the visualization updates live",
      you: "You", tutor: "Tutor", thinking: "Thinking…", generating: "Generating…", remove: "Remove",
      explain_scene: "Explain what I'm seeing", what_sliders: "What do the sliders change?",
      equation_mean: "What does the equation mean?", solve_steps: "Solve it step by step",
      switch_light: "Switch to light theme", switch_dark: "Switch to dark theme",
      ai_writing: "The AI is writing a custom animation for your prompt…",
      coach_welcome: "Enter a STEM idea, press Visualize, then ask me what changes and why.",
      chem_balance: "Chemistry • balanced equation — reactants → products, atoms conserved",
      chem_molecule: "Chemistry • 3D molecular structure — drag to orbit, scroll to zoom",
      demo_status: "{{area}} demo • drag the sliders to explore", worked_solution: "Worked solution • step-by-step slides — solved with your own numbers",
      browser_help: "Browser edition • free-form AI generation runs in the desktop app — try a formula, reaction, or curriculum topic",
      curated_status: "{{dimension}} • curated STEM scene (instant, verified)",
    },
    zh: {
      language: "语言", app_subtitle: "动画 STEM 学习工作室",
      explanation: "讲解", examples_playback: "示例与播放", resources: "资源",
      concept: "概念", scene: "场景", equation_rule: "公式 / 规则", waiting: "等待中…", auto: "自动",
      what_seeing: "你看到的内容",
      browser_intro: "浏览器版完全在本机运行，无需服务器。输入化学式、反应式或课程主题，然后点击“可视化”。",
      server_intro: "输入任意 STEM 概念，然后点击“可视化”。AI 会创建自定义动画并在此讲解。",
      learning_checkpoints: "学习检查点", observe_default: "先观察运动，并找出发生变化的量。",
      adjust_default: "调整一个数值，在重播前预测结果。", explain_default: "用自己的话解释规律，以检查理解程度。",
      playback: "播放控制", pause: "暂停", play: "播放", speed: "速度", try_example: "尝试示例",
      study_packs: "学习包", import_pack: "导入学习包", all_packs: "← 所有学习包",
      start_lesson: "开始课程", question_heading: "你想理解什么？", prompt_help: "输入公式、反应式、主题或解题问题。",
      describe: "描述", describe_help: "你想探索的概念。", observe: "观察", observe_help: "动画并改变其中的数值。",
      question: "提问", question_help: "使用学习教练探究结果。", prompt: "提示", prefer: "偏好",
      visualize: "可视化", surprise: "随机探索", tip: "提示：每次只改变一个变量。按 Cmd/Ctrl + Enter 运行。",
      reflect_practise: "反思与练习", learning_coach: "学习教练",
      browser_coach_desc: "询问提示、比较或下一步问题。完整 AI 辅导可在桌面应用中使用。",
      server_coach_desc: "根据当前场景询问提示、比较或下一步问题。", ask_tutor: "询问教练",
      browser_placeholder: "先尝试上方的公式、反应式或主题，再询问结果。", server_placeholder: "询问曲线为何弯曲、各力的含义，或如何解决类似问题。",
      browser_chat_hint: "浏览器版：课程指导可离线使用。", server_chat_hint: "教练会结合当前可视化内容回答。",
      ask: "提问", quick_questions: "快捷问题", checking: "检查中…", detecting: "检测中…",
      idle_formula: "空闲 — 输入公式、反应式或主题。", idle_prompt: "空闲 — 输入提示以开始。",
      orbit_hint: "拖动旋转 · 滚动缩放 · 双击重置", browser_edition: "浏览器版",
      browser_features: "化学 · 互动演示 · 分步解题 · 浏览器内运行", code_only: "纯代码模式", server_offline: "服务器离线",
      online: "在线", generator: "生成器", no_equation: "无单一公式 — 概念场景", adjust_values: "调整数值 — 可视化会实时更新",
      you: "你", tutor: "教练", thinking: "思考中…", generating: "生成中…", remove: "移除",
      explain_scene: "解释我看到的内容", what_sliders: "滑块会改变什么？", equation_mean: "这个公式是什么意思？",
      solve_steps: "分步解题", switch_light: "切换到浅色主题", switch_dark: "切换到深色主题",
      ai_writing: "AI 正在为你的提示编写自定义动画…",
      coach_welcome: "输入一个 STEM 概念，点击“可视化”，然后问我发生了什么变化以及原因。",
      chem_balance: "化学 • 已配平反应式 — 反应物 → 生成物，原子守恒", chem_molecule: "化学 • 3D 分子结构 — 拖动旋转，滚动缩放",
      demo_status: "{{area}} 演示 • 拖动滑块进行探索", worked_solution: "解题过程 • 分步动画 — 使用你的数值求解",
      browser_help: "浏览器版 • 自由 AI 生成可在桌面应用中使用 — 请尝试公式、反应式或课程主题", curated_status: "{{dimension}} • 精选 STEM 场景（即时、已验证）",
    },
    es: {
      language: "Idioma", app_subtitle: "Estudio STEM animado", explanation: "Explicación",
      examples_playback: "Ejemplos y reproducción", resources: "Recursos", concept: "Concepto", scene: "Escena",
      equation_rule: "Ecuación / regla", waiting: "Esperando…", auto: "Automático", what_seeing: "Lo que estás viendo",
      browser_intro: "La edición web funciona por completo en tu navegador, sin servidor. Introduce una fórmula química, reacción o tema y pulsa Visualizar.",
      server_intro: "Introduce cualquier idea STEM y pulsa Visualizar. La IA creará una animación personalizada y la explicará aquí.",
      learning_checkpoints: "Puntos de aprendizaje", observe_default: "Observa primero el movimiento e identifica qué cambia.",
      adjust_default: "Cambia un valor y predice el resultado antes de repetir.", explain_default: "Explica el patrón con tus palabras para comprobar tu comprensión.",
      playback: "Reproducción", pause: "Pausar", play: "Reproducir", speed: "Velocidad", try_example: "Probar un ejemplo",
      study_packs: "Paquetes de estudio", import_pack: "Importar un paquete", all_packs: "← Todos los paquetes",
      start_lesson: "Iniciar una lección", question_heading: "¿Qué quieres comprender?", prompt_help: "Introduce una fórmula, reacción, tema o problema resuelto.",
      describe: "Describe", describe_help: "la idea que quieres explorar.", observe: "Observa", observe_help: "la animación y cambia sus valores.",
      question: "Pregunta", question_help: "sobre el resultado al tutor.", prompt: "Indicación", prefer: "Preferir", visualize: "Visualizar",
      surprise: "Sorpréndeme", tip: "Consejo: cambia una variable cada vez. Pulsa Cmd/Ctrl + Enter para ejecutar.",
      reflect_practise: "Reflexiona y practica", learning_coach: "Tutor de aprendizaje",
      browser_coach_desc: "Pide una pista, comparación o pregunta siguiente. La tutoría completa con IA está en la aplicación de escritorio.",
      server_coach_desc: "Pide una pista, comparación o pregunta siguiente basada en la escena actual.", ask_tutor: "Preguntar al tutor",
      browser_placeholder: "Prueba arriba una fórmula, reacción o tema y pregunta sobre el resultado.", server_placeholder: "Pregunta por qué se curva la gráfica, qué significa cada fuerza o cómo resolver un problema similar.",
      browser_chat_hint: "Edición web: la orientación funciona sin conexión.", server_chat_hint: "El tutor usa la visualización actual como contexto.",
      ask: "Preguntar", quick_questions: "Preguntas rápidas", checking: "Comprobando…", detecting: "Detectando…",
      idle_formula: "En espera — introduce una fórmula, reacción o tema.", idle_prompt: "En espera — introduce una indicación para empezar.",
      orbit_hint: "arrastra para girar · desplaza para ampliar · doble clic para restablecer", browser_edition: "Edición web",
      browser_features: "Química · demos interactivas · solución paso a paso · en tu navegador", code_only: "Solo código", server_offline: "Servidor sin conexión",
      online: "en línea", generator: "Generador", no_equation: "Sin ecuación única — escena conceptual", adjust_values: "Ajusta los valores — la visualización se actualiza al instante",
      you: "Tú", tutor: "Tutor", thinking: "Pensando…", generating: "Generando…", remove: "Eliminar",
      explain_scene: "Explica lo que estoy viendo", what_sliders: "¿Qué cambian los controles?", equation_mean: "¿Qué significa la ecuación?",
      solve_steps: "Resolver paso a paso", switch_light: "Cambiar al tema claro", switch_dark: "Cambiar al tema oscuro",
      ai_writing: "La IA está creando una animación personalizada para tu indicación…",
      coach_welcome: "Introduce una idea STEM, pulsa Visualizar y pregúntame qué cambia y por qué.",
      chem_balance: "Química • ecuación ajustada — reactivos → productos, átomos conservados", chem_molecule: "Química • estructura molecular 3D — arrastra para girar y desplaza para ampliar",
      demo_status: "Demo de {{area}} • mueve los controles para explorar", worked_solution: "Solución • diapositivas paso a paso con tus propios valores",
      browser_help: "Edición web • la generación libre con IA está en la aplicación de escritorio — prueba una fórmula, reacción o tema", curated_status: "{{dimension}} • escena STEM seleccionada (instantánea y verificada)",
    },
    hi: {
      language: "भाषा", app_subtitle: "एनिमेटेड STEM स्टूडियो", explanation: "व्याख्या", examples_playback: "उदाहरण और प्लेबैक",
      resources: "संसाधन", concept: "अवधारणा", scene: "दृश्य", equation_rule: "समीकरण / नियम", waiting: "प्रतीक्षा…", auto: "स्वचालित",
      what_seeing: "आप क्या देख रहे हैं", browser_intro: "ब्राउज़र संस्करण पूरी तरह आपके ब्राउज़र में चलता है। रासायनिक सूत्र, अभिक्रिया या पाठ्य विषय दर्ज करें और विज़ुअलाइज़ दबाएँ।",
      server_intro: "कोई भी STEM विचार दर्ज करें और विज़ुअलाइज़ दबाएँ। AI एक विशेष एनिमेशन बनाकर यहाँ समझाएगा।",
      learning_checkpoints: "सीखने की जाँच", observe_default: "पहले गति देखें और पहचानें कि क्या बदलता है।",
      adjust_default: "एक मान बदलें और दोबारा चलाने से पहले परिणाम का अनुमान लगाएँ।", explain_default: "समझ जाँचने के लिए पैटर्न को अपने शब्दों में समझाएँ।",
      playback: "प्लेबैक", pause: "रोकें", play: "चलाएँ", speed: "गति", try_example: "उदाहरण आज़माएँ",
      study_packs: "अध्ययन पैक", import_pack: "पैक आयात करें", all_packs: "← सभी पैक", start_lesson: "पाठ शुरू करें",
      question_heading: "आप क्या समझना चाहते हैं?", prompt_help: "सूत्र, अभिक्रिया, विषय या हल किया हुआ प्रश्न दर्ज करें।",
      describe: "वर्णन करें", describe_help: "उस विचार का जिसे आप जानना चाहते हैं।", observe: "देखें", observe_help: "एनिमेशन और उसके मान बदलें।",
      question: "प्रश्न करें", question_help: "परिणाम के बारे में लर्निंग कोच से।", prompt: "प्रॉम्प्ट", prefer: "वरीयता",
      visualize: "विज़ुअलाइज़", surprise: "कुछ नया दिखाएँ", tip: "सुझाव: एक बार में एक ही चर बदलें। चलाने के लिए Cmd/Ctrl + Enter दबाएँ।",
      reflect_practise: "सोचें और अभ्यास करें", learning_coach: "लर्निंग कोच",
      browser_coach_desc: "संकेत, तुलना या अगला प्रश्न पूछें। पूर्ण AI ट्यूशन डेस्कटॉप ऐप में उपलब्ध है।",
      server_coach_desc: "वर्तमान दृश्य के आधार पर संकेत, तुलना या अगला प्रश्न पूछें।", ask_tutor: "कोच से पूछें",
      browser_placeholder: "ऊपर कोई सूत्र, अभिक्रिया या विषय आज़माएँ, फिर परिणाम के बारे में पूछें।", server_placeholder: "पूछें कि वक्र क्यों मुड़ता है, हर बल का अर्थ क्या है या ऐसा प्रश्न कैसे हल करें।",
      browser_chat_hint: "ब्राउज़र संस्करण: पाठ मार्गदर्शन ऑफ़लाइन चलता है।", server_chat_hint: "कोच वर्तमान विज़ुअलाइज़ेशन को संदर्भ मानता है।",
      ask: "पूछें", quick_questions: "त्वरित प्रश्न", checking: "जाँच हो रही है…", detecting: "पता लगाया जा रहा है…",
      idle_formula: "तैयार — सूत्र, अभिक्रिया या विषय दर्ज करें।", idle_prompt: "तैयार — शुरू करने के लिए प्रॉम्प्ट दर्ज करें।",
      orbit_hint: "घुमाने के लिए खींचें · ज़ूम के लिए स्क्रॉल · रीसेट के लिए डबल-क्लिक", browser_edition: "ब्राउज़र संस्करण",
      browser_features: "रसायन · इंटरैक्टिव डेमो · चरणबद्ध हल · ब्राउज़र में चलता है", code_only: "केवल कोड", server_offline: "सर्वर ऑफ़लाइन",
      online: "ऑनलाइन", generator: "जेनरेटर", no_equation: "एकल समीकरण नहीं — अवधारणा दृश्य", adjust_values: "मान बदलें — दृश्य तुरंत अपडेट होता है",
      you: "आप", tutor: "कोच", thinking: "सोच रहा है…", generating: "बन रहा है…", remove: "हटाएँ",
      explain_scene: "मैं जो देख रहा हूँ उसे समझाएँ", what_sliders: "स्लाइडर क्या बदलते हैं?", equation_mean: "समीकरण का क्या अर्थ है?",
      solve_steps: "चरणबद्ध हल करें", switch_light: "हल्की थीम पर जाएँ", switch_dark: "गहरी थीम पर जाएँ",
      ai_writing: "AI आपके प्रॉम्प्ट के लिए विशेष एनिमेशन बना रहा है…",
      coach_welcome: "कोई STEM विचार दर्ज करें, विज़ुअलाइज़ दबाएँ और फिर पूछें कि क्या बदलता है और क्यों।",
      chem_balance: "रसायन • संतुलित समीकरण — अभिकारक → उत्पाद, परमाणु संरक्षित", chem_molecule: "रसायन • 3D आणविक संरचना — घुमाने के लिए खींचें, ज़ूम के लिए स्क्रॉल करें",
      demo_status: "{{area}} डेमो • जानने के लिए स्लाइडर चलाएँ", worked_solution: "हल • आपके मानों के साथ चरणबद्ध स्लाइड",
      browser_help: "ब्राउज़र संस्करण • मुक्त AI निर्माण डेस्कटॉप ऐप में है — सूत्र, अभिक्रिया या विषय आज़माएँ", curated_status: "{{dimension}} • चुना हुआ STEM दृश्य (तुरंत, सत्यापित)",
    },
    fr: {
      language: "Langue", app_subtitle: "Studio STEM animé", explanation: "Explication", examples_playback: "Exemples et lecture",
      resources: "Ressources", concept: "Concept", scene: "Scène", equation_rule: "Équation / règle", waiting: "En attente…", auto: "Auto",
      what_seeing: "Ce que vous observez", browser_intro: "La version web fonctionne entièrement dans votre navigateur, sans serveur. Saisissez une formule chimique, une réaction ou un sujet, puis cliquez sur Visualiser.",
      server_intro: "Saisissez une idée STEM, puis cliquez sur Visualiser. L’IA créera une animation personnalisée et l’expliquera ici.",
      learning_checkpoints: "Repères d’apprentissage", observe_default: "Observez d’abord le mouvement et repérez ce qui change.",
      adjust_default: "Modifiez une valeur et prévoyez le résultat avant de relancer.", explain_default: "Expliquez le phénomène avec vos propres mots pour vérifier votre compréhension.",
      playback: "Lecture", pause: "Pause", play: "Lire", speed: "Vitesse", try_example: "Essayer un exemple",
      study_packs: "Packs d’étude", import_pack: "Importer un pack", all_packs: "← Tous les packs", start_lesson: "Commencer une leçon",
      question_heading: "Que voulez-vous comprendre ?", prompt_help: "Saisissez une formule, une réaction, un sujet ou un problème à résoudre.",
      describe: "Décrire", describe_help: "l’idée que vous souhaitez explorer.", observe: "Observer", observe_help: "l’animation et modifier ses valeurs.",
      question: "Questionner", question_help: "le résultat avec le coach d’apprentissage.", prompt: "Consigne", prefer: "Préférer",
      visualize: "Visualiser", surprise: "Surprenez-moi", tip: "Conseil : ne changez qu’une variable à la fois. Cmd/Ctrl + Entrée pour lancer.",
      reflect_practise: "Réfléchir et s’exercer", learning_coach: "Coach d’apprentissage",
      browser_coach_desc: "Demandez un indice, une comparaison ou une question suivante. Le tutorat IA complet est disponible dans l’application de bureau.",
      server_coach_desc: "Demandez un indice, une comparaison ou une question suivante liée à la scène actuelle.", ask_tutor: "Demander au coach",
      browser_placeholder: "Essayez une formule, une réaction ou un sujet ci-dessus, puis interrogez le résultat.", server_placeholder: "Demandez pourquoi la courbe se plie, ce que signifie chaque force ou comment résoudre un problème similaire.",
      browser_chat_hint: "Version web : le guidage pédagogique fonctionne hors ligne.", server_chat_hint: "Le coach utilise la visualisation actuelle comme contexte.",
      ask: "Demander", quick_questions: "Questions rapides", checking: "Vérification…", detecting: "Détection…",
      idle_formula: "En attente — saisissez une formule, une réaction ou un sujet.", idle_prompt: "En attente — saisissez une consigne pour commencer.",
      orbit_hint: "glisser pour pivoter · défiler pour zoomer · double-cliquer pour réinitialiser", browser_edition: "Version web",
      browser_features: "Chimie · démos interactives · résolution pas à pas · dans votre navigateur", code_only: "Code uniquement", server_offline: "Serveur hors ligne",
      online: "en ligne", generator: "Générateur", no_equation: "Aucune équation unique — scène conceptuelle", adjust_values: "Modifiez les valeurs — la visualisation se met à jour instantanément",
      you: "Vous", tutor: "Coach", thinking: "Réflexion…", generating: "Génération…", remove: "Supprimer",
      explain_scene: "Expliquer ce que je vois", what_sliders: "Que modifient les curseurs ?", equation_mean: "Que signifie l’équation ?",
      solve_steps: "Résoudre pas à pas", switch_light: "Passer au thème clair", switch_dark: "Passer au thème sombre",
      ai_writing: "L’IA crée une animation personnalisée pour votre consigne…",
      coach_welcome: "Saisissez une idée STEM, cliquez sur Visualiser, puis demandez-moi ce qui change et pourquoi.",
      chem_balance: "Chimie • équation équilibrée — réactifs → produits, atomes conservés", chem_molecule: "Chimie • structure moléculaire 3D — glisser pour pivoter, défiler pour zoomer",
      demo_status: "Démo {{area}} • déplacez les curseurs pour explorer", worked_solution: "Solution • diapositives pas à pas avec vos propres valeurs",
      browser_help: "Version web • la génération libre par IA est dans l’application de bureau — essayez une formule, réaction ou sujet", curated_status: "{{dimension}} • scène STEM sélectionnée (instantanée et vérifiée)",
    },
    de: {
      language: "Sprache", app_subtitle: "Animiertes STEM-Studio", explanation: "Erklärung", examples_playback: "Beispiele und Wiedergabe",
      resources: "Ressourcen", concept: "Konzept", scene: "Szene", equation_rule: "Gleichung / Regel", waiting: "Warten…", auto: "Automatisch",
      what_seeing: "Was du siehst", browser_intro: "Die Browser-Version läuft vollständig und ohne Server in deinem Browser. Gib eine chemische Formel, Reaktion oder ein Unterrichtsthema ein und klicke auf Visualisieren.",
      server_intro: "Gib ein beliebiges STEM-Thema ein und klicke auf Visualisieren. Die KI erstellt eine eigene Animation und erklärt sie hier.",
      learning_checkpoints: "Lernkontrolle", observe_default: "Beobachte zuerst die Bewegung und erkenne, was sich verändert.",
      adjust_default: "Ändere einen Wert und sage das Ergebnis vor der Wiederholung voraus.", explain_default: "Erkläre das Muster mit eigenen Worten, um dein Verständnis zu prüfen.",
      playback: "Wiedergabe", pause: "Pause", play: "Abspielen", speed: "Geschwindigkeit", try_example: "Beispiel ausprobieren",
      study_packs: "Lernpakete", import_pack: "Paket importieren", all_packs: "← Alle Pakete", start_lesson: "Lektion beginnen",
      question_heading: "Was möchtest du verstehen?", prompt_help: "Gib eine Formel, Reaktion, ein Thema oder eine Aufgabe ein.",
      describe: "Beschreiben", describe_help: "welche Idee du untersuchen möchtest.", observe: "Beobachten", observe_help: "wie die Animation auf geänderte Werte reagiert.",
      question: "Hinterfragen", question_help: "das Ergebnis mit dem Lerncoach.", prompt: "Eingabe", prefer: "Bevorzugt",
      visualize: "Visualisieren", surprise: "Überrasch mich", tip: "Tipp: Ändere jeweils nur eine Variable. Mit Cmd/Ctrl + Enter starten.",
      reflect_practise: "Nachdenken und üben", learning_coach: "Lerncoach",
      browser_coach_desc: "Bitte um einen Hinweis, Vergleich oder eine Anschlussfrage. Vollständiges KI-Tutoring gibt es in der Desktop-App.",
      server_coach_desc: "Bitte um einen Hinweis, Vergleich oder eine Anschlussfrage zur aktuellen Szene.", ask_tutor: "Lerncoach fragen",
      browser_placeholder: "Probiere oben eine Formel, Reaktion oder ein Thema aus und frage dann nach dem Ergebnis.", server_placeholder: "Frage, warum sich die Kurve biegt, was jede Kraft bedeutet oder wie man eine ähnliche Aufgabe löst.",
      browser_chat_hint: "Browser-Version: Lernhinweise funktionieren offline.", server_chat_hint: "Der Coach nutzt die aktuelle Visualisierung als Kontext.",
      ask: "Fragen", quick_questions: "Schnelle Fragen", checking: "Wird geprüft…", detecting: "Wird erkannt…",
      idle_formula: "Bereit — Formel, Reaktion oder Thema eingeben.", idle_prompt: "Bereit — Eingabe zum Starten machen.",
      orbit_hint: "ziehen zum Drehen · scrollen zum Zoomen · Doppelklick zum Zurücksetzen", browser_edition: "Browser-Version",
      browser_features: "Chemie · interaktive Demos · schrittweise Lösungen · im Browser", code_only: "Nur Code", server_offline: "Server offline",
      online: "online", generator: "Generator", no_equation: "Keine einzelne Gleichung — Konzeptszene", adjust_values: "Werte ändern — die Visualisierung aktualisiert sich sofort",
      you: "Du", tutor: "Coach", thinking: "Denkt nach…", generating: "Wird erstellt…", remove: "Entfernen",
      explain_scene: "Erkläre, was ich sehe", what_sliders: "Was verändern die Regler?", equation_mean: "Was bedeutet die Gleichung?",
      solve_steps: "Schrittweise lösen", switch_light: "Zum hellen Design wechseln", switch_dark: "Zum dunklen Design wechseln",
      ai_writing: "Die KI erstellt eine individuelle Animation für deine Eingabe…",
      coach_welcome: "Gib ein STEM-Thema ein, klicke auf Visualisieren und frage mich dann, was sich ändert und warum.",
      chem_balance: "Chemie • ausgeglichene Gleichung — Edukte → Produkte, Atome bleiben erhalten", chem_molecule: "Chemie • 3D-Molekülstruktur — ziehen zum Drehen, scrollen zum Zoomen",
      demo_status: "{{area}}-Demo • Regler bewegen und erkunden", worked_solution: "Lösung • schrittweise Folien mit deinen eigenen Werten",
      browser_help: "Browser-Version • freie KI-Erstellung gibt es in der Desktop-App — probiere Formel, Reaktion oder Thema", curated_status: "{{dimension}} • ausgewählte STEM-Szene (sofort, geprüft)",
    },
  };

  function normalize(value) {
    const short = String(value || "").toLowerCase().split("-")[0];
    return SUPPORTED.includes(short) ? short : "en";
  }

  let locale = "en";
  try {
    locale = normalize(localStorage.getItem(STORAGE_KEY) || navigator.language);
  } catch (error) {
    locale = normalize(navigator.language);
  }

  function t(key, vars) {
    let value = (MESSAGES[locale] && MESSAGES[locale][key]) || MESSAGES.en[key] || key;
    Object.entries(vars || {}).forEach(([name, replacement]) => {
      value = value.replaceAll(`{{${name}}}`, String(replacement));
    });
    return value;
  }

  function translateDocument(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((node) => {
      node.textContent = t(node.dataset.i18n);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
    });
    scope.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
      node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((node) => {
      node.setAttribute("title", t(node.dataset.i18nTitle));
    });
    document.documentElement.lang = locale === "zh" ? "zh-CN" : locale;
    const select = document.getElementById("languageSelect");
    if (select) select.value = locale;
  }

  function setLocale(next, persist) {
    const normalized = normalize(next);
    if (normalized === locale) return;
    locale = normalized;
    if (persist !== false) {
      try { localStorage.setItem(STORAGE_KEY, locale); } catch (error) { /* unavailable */ }
    }
    translateDocument();
    window.dispatchEvent(new CustomEvent("visuallm:languagechange", { detail: { locale } }));
  }

  function init() {
    const select = document.getElementById("languageSelect");
    if (select) {
      select.value = locale;
      select.addEventListener("change", (event) => setLocale(event.target.value));
    }
    translateDocument();
  }

  window.VisualLMI18n = {
    current: () => locale,
    languages: () => ({ ...LANGUAGE_NAMES }),
    normalize,
    setLocale,
    t,
    translateDocument,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
