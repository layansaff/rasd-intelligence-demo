# RASD Intelligence portfolio kit

Use this page to present the project consistently in a portfolio, interview, or LinkedIn post. The public demo is for fictional data only and its scoring model is illustrative.

## One-sentence description

RASD Intelligence is a full-stack supplier risk and business continuity prototype that turns bounded disruption inputs into explainable risk factors, recovery gaps, and review actions.

## Short project brief

**Challenge:** Supplier disruption assessments can be difficult to compare and turn into continuity actions.

**Solution:** A responsive interface collects defined inputs, while a FastAPI service validates them and returns a transparent rules-based assessment with a factor breakdown and recovery recommendations.

**Engineering:** Python, FastAPI, Pydantic, SQLite for local mode, HTML/CSS/JavaScript, Docker Compose, GitHub Actions, and Render.

**Responsible design:** The public demo does not persist visitor assessments on the server. The score is explicitly preliminary, deterministic, and not independently validated.

## 60-second demo walkthrough

1. Open the [live demo](https://rasd-intelligence-demo.onrender.com/ui) and point out the public-demo notice.
2. Start a risk assessment and use fictional supplier and process details.
3. Change impact, disruption likelihood, control effectiveness, supplier dependency, and recovery hours.
4. Submit the assessment and explain how the result exposes its score, contributing factors, recovery gap, and recommended actions.
5. Show that the result is temporary and that the scoring method is a transparent prototype, not an automated business decision.

## LinkedIn draft · English

I built **RASD Intelligence**, a portfolio project exploring how supplier disruption risk can be presented in a way that is easier to review and act on.

The app brings together a responsive assessment interface and a FastAPI service. It validates inputs, explains the factors behind a preliminary risk score, highlights recovery gaps, and suggests continuity actions. I also set up a stateless public demo, local SQLite mode, Docker Compose, and automated CI checks.

The scoring model is intentionally transparent and illustrative; it has not been calibrated or independently validated. The public demo stores no visitor assessments on the server, so please use fictional data.

Try it: https://rasd-intelligence-demo.onrender.com/ui
Explore the code: https://github.com/layansaff/rasd-intelligence-demo

I’d welcome feedback from people working in risk, resilience, business continuity, or software engineering.

## مسودة LinkedIn · العربية

أنجزت **RASD Intelligence**، وهو مشروع محفظة يستكشف طريقة أوضح لمراجعة مخاطر تعطل المورّد وربطها بإجراءات استمرارية الأعمال.

يجمع التطبيق بين واجهة تقييم متجاوبة وواجهة خلفية مبنية بـFastAPI. يتحقق من المدخلات، ويشرح عوامل درجة المخاطر التقديرية، ويبرز فجوة التعافي، ويقترح إجراءات للمراجعة. كما أعددت عرضًا عامًا لا يحفظ تقييمات الزوار على الخادم، ووضعًا محليًا باستخدام SQLite، وتشغيلًا عبر Docker، وفحوصًا آلية عبر GitHub Actions.

نموذج التقييم توضيحي وشفاف، ولم تتم معايرته أو مراجعته بصورة مستقلة. استخدموا بيانات وهمية عند تجربة العرض العام.

جرّبوه: https://rasd-intelligence-demo.onrender.com/ui
الكود والتفاصيل: https://github.com/layansaff/rasd-intelligence-demo

يسعدني استقبال الملاحظات من العاملين في إدارة المخاطر والمرونة واستمرارية الأعمال وهندسة البرمجيات.
