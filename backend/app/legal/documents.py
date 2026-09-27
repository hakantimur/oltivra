"""Terms of Service and Privacy Policy (spec §2.1, §23.1, §30, §31, store readiness).

The texts describe what the system actually does; when behaviour changes, update the text and bump the matching
version in ``app.profiles.service`` so players re-accept. Operator identity, contact and governing law come from
settings (required outside dev/test) so no placeholder ever reaches production.

Each document is a list of sections ``(heading, [paragraph, ...])``; ``{operator}``, ``{contact}``, ``{address}``,
``{law}`` and ``{effective}`` are filled at render time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocName = Literal["terms", "privacy"]
Section = tuple[str, list[str]]

TERMS_EN: list[Section] = [
    ("1. Who we are", [
        "Oltivra is a live multiplayer trivia game operated by {operator}{address}. These Terms form an agreement "
        "between you and {operator}. Contact: {contact}.",
        "Oltivra shares one sign-in (the shared Synova account) with other participating Synova products.",
    ]),
    ("2. Who can play", [
        "You must be at least 13 years old to use Oltivra. If the law where you live sets a higher age for using "
        "online services without parental consent, you must meet that age or have your parent's or guardian's "
        "permission. We do not ask for your date of birth; you confirm your age when you start.",
    ]),
    ("3. Your account", [
        "You sign in with Google, Apple or email. You are responsible for keeping access to your sign-in method "
        "secure and for activity on your account. One person may not use another person's account.",
        "Your player name must be unique and must not be offensive, misleading, impersonate someone else or "
        "include personal contact details. We may require you to choose a new name. After a name change or "
        "account deletion, the previous name stays reserved for 30 days.",
    ]),
    ("4. How matches work", [
        "Quick Battle is a four-player match of ten questions where the first correct answer scores; a wrong "
        "answer costs points and locks you out of that round. Survival is a ten-player elimination match. Our "
        "servers decide timing, correctness, scores, rankings and rewards; the app only displays them.",
        "Computer-controlled opponents: to keep waiting times short, some seats in public matches may be filled by "
        "computer-controlled players. They use normal player names and avatars and play at set skill levels. They "
        "never replace real players who are already matched, their results do not change any real player's "
        "statistics, and ranked eligibility follows the published ranked rules.",
        "Private challenges you create with friends only include the people you invite.",
    ]),
    ("5. Fair play", [
        "You must not cheat or try to gain an unfair advantage. This includes using bots, scripts, automation or "
        "modified clients; looking up answers with tools designed to automate play; sharing answers during a match; "
        "manipulating matchmaking or leaderboards; using several accounts to affect rankings or rewards; exploiting "
        "bugs; or interfering with the service.",
        "We use automated signals (for example answer timing and request patterns) together with human review to "
        "detect abuse. Automated measures are limited to temporary restrictions; permanent bans are decided by a "
        "person.",
    ]),
    ("6. Community rules, reports and blocks", [
        "Reactions in matches are limited to a fixed set of emoji and short phrases. You must not harass, threaten "
        "or abuse other players, including through player names.",
        "You can block players and report players or questions from within the app. We review reports and may take "
        "action against accounts or content.",
    ]),
    ("7. Enforcement", [
        "If you break these Terms we may, depending on severity: require a name change, restrict matchmaking or "
        "ranked play for a period, suspend your account, or permanently ban it. Where possible we tell you why. "
        "You can contact {contact} if you believe a decision is wrong.",
    ]),
    ("8. Progress and virtual items", [
        "XP, levels, leagues, leaderboard positions, badges and frames are game features without monetary value. "
        "They cannot be sold, transferred or exchanged for money. Weekly leaderboards and leagues reset on the "
        "published schedule.",
    ]),
    ("9. Advertising and rewarded videos", [
        "Oltivra is supported by ads. Ads are shown only after a match result is visible and never during a "
        "question. Watching a rewarded video is always optional and can give bonus XP for that match; it never "
        "affects rankings, leagues or match results.",
    ]),
    ("10. Purchases", [
        "The one-time Remove Ads purchase removes interstitial ads from your account. Purchases are processed by "
        "Google Play or the App Store under their terms, including their refund policies. Purchases are linked to "
        "your account and can be restored on another device with the same account.",
    ]),
    ("11. Questions and content", [
        "We work to keep questions accurate, but some may contain mistakes or become outdated. You can report a "
        "question from the match screen. The app, its questions, designs and software belong to {operator} or its "
        "licensors; you may use them only to play Oltivra.",
    ]),
    ("12. Availability", [
        "We may change, pause or discontinue features. If a match cannot continue safely (for example after a "
        "server problem) it may be cancelled without affecting your ranking.",
    ]),
    ("13. Ending your account", [
        "You can delete your account at any time in Settings or on our web deletion page. Because the sign-in is "
        "shared, deleting it removes the shared Synova account across participating products. We may close accounts "
        "that seriously or repeatedly break these Terms.",
    ]),
    ("14. Liability", [
        "Oltivra is provided as is. To the extent permitted by law, {operator} is not liable for indirect or "
        "consequential losses, or for losses caused by events outside its reasonable control. Nothing in these "
        "Terms limits rights you have as a consumer under mandatory law.",
    ]),
    ("15. Changes and governing law", [
        "We may update these Terms. When we do, we change the version and ask you to accept the new Terms before "
        "you continue to play. These Terms are governed by {law}, without affecting mandatory consumer protections "
        "of the country where you live.",
        "Effective date: {effective}.",
    ]),
]

TERMS_TR: list[Section] = [
    ("1. Biz kimiz", [
        "Oltivra, {operator}{address} tarafından işletilen canlı, çok oyunculu bir bilgi yarışması oyunudur. Bu "
        "Koşullar seninle {operator} arasında bir sözleşmedir. İletişim: {contact}.",
        "Oltivra, diğer Synova ürünleriyle tek bir girişi (ortak Synova hesabı) paylaşır.",
    ]),
    ("2. Kimler oynayabilir", [
        "Oltivra'yı kullanmak için en az 13 yaşında olmalısın. Yaşadığın yerde çevrimiçi hizmetleri ebeveyn izni "
        "olmadan kullanmak için daha yüksek bir yaş sınırı varsa, o yaşta olmalı ya da ebeveyninin veya vasinin "
        "iznini almalısın. Doğum tarihini sormayız; başlarken yaşını onaylarsın.",
    ]),
    ("3. Hesabın", [
        "Google, Apple veya e-posta ile giriş yaparsın. Giriş yöntemine erişimini güvende tutmak ve hesabındaki "
        "etkinlikler senin sorumluluğundadır. Bir kişi başkasının hesabını kullanamaz.",
        "Oyuncu adın benzersiz olmalı; saldırgan, yanıltıcı, başkasını taklit eden veya kişisel iletişim bilgisi "
        "içeren bir ad olamaz. Yeni bir ad seçmeni isteyebiliriz. Ad değişikliğinden veya hesap silindikten sonra "
        "eski ad 30 gün boyunca ayrılmış kalır.",
    ]),
    ("4. Maçlar nasıl işler", [
        "Hızlı Düello, dört oyunculu ve on sorudan oluşan bir maçtır; ilk doğru cevap puan alır, yanlış cevap puan "
        "kaybettirir ve seni o turdan çıkarır. Hayatta Kalma on oyunculu bir eleme maçıdır. Süreyi, doğruluğu, "
        "puanları, sıralamaları ve ödülleri sunucularımız belirler; uygulama yalnızca gösterir.",
        "Bilgisayar kontrollü rakipler: bekleme süresini kısa tutmak için herkese açık maçlarda bazı koltuklar "
        "bilgisayar kontrollü oyuncularla doldurulabilir. Bu oyuncular normal oyuncu adları ve avatarları kullanır "
        "ve belirli beceri seviyelerinde oynar. Eşleşmiş gerçek oyuncuların yerini asla almazlar, sonuçları hiçbir "
        "gerçek oyuncunun istatistiğini değiştirmez ve dereceli uygunluk yayımlanan dereceli kurallara göre "
        "belirlenir.",
        "Arkadaşlarınla oluşturduğun özel meydan okumalarda yalnızca davet ettiğin kişiler bulunur.",
    ]),
    ("5. Adil oyun", [
        "Hile yapamaz veya haksız avantaj elde etmeye çalışamazsın. Buna bot, betik, otomasyon veya değiştirilmiş "
        "istemci kullanmak; oyunu otomatikleştirmek için tasarlanmış araçlarla cevap aramak; maç sırasında cevap "
        "paylaşmak; eşleştirmeyi veya sıralamaları manipüle etmek; sıralamaları ya da ödülleri etkilemek için birden "
        "fazla hesap kullanmak; hatalardan yararlanmak veya hizmete müdahale etmek dahildir.",
        "Kötüye kullanımı tespit etmek için otomatik sinyalleri (örneğin cevap süreleri ve istek örüntüleri) insan "
        "incelemesiyle birlikte kullanırız. Otomatik önlemler geçici kısıtlamalarla sınırlıdır; kalıcı yasaklara bir "
        "insan karar verir.",
    ]),
    ("6. Topluluk kuralları, bildirimler ve engellemeler", [
        "Maç içi tepkiler sabit bir emoji ve kısa ifade listesiyle sınırlıdır. Oyuncu adları dahil hiçbir yolla "
        "diğer oyuncuları taciz edemez, tehdit edemez veya onlara hakaret edemezsin.",
        "Uygulama içinden oyuncuları engelleyebilir, oyuncuları veya soruları bildirebilirsin. Bildirimleri inceler, "
        "hesaplar veya içerik hakkında işlem yapabiliriz.",
    ]),
    ("7. Yaptırımlar", [
        "Bu Koşulları ihlal edersen, ihlalin ağırlığına göre ad değişikliği isteyebilir, eşleştirmeyi veya dereceli "
        "oyunu bir süreliğine kısıtlayabilir, hesabını askıya alabilir ya da kalıcı olarak yasaklayabiliriz. Mümkün "
        "olduğunda nedenini bildiririz. Bir kararın hatalı olduğunu düşünüyorsan {contact} adresine yazabilirsin.",
    ]),
    ("8. İlerleme ve sanal öğeler", [
        "XP, seviyeler, ligler, sıralama konumları, rozetler ve çerçeveler parasal değeri olmayan oyun özellikleridir. "
        "Satılamaz, devredilemez veya paraya çevrilemez. Haftalık sıralamalar ve ligler yayımlanan takvime göre "
        "sıfırlanır.",
    ]),
    ("9. Reklamlar ve ödüllü videolar", [
        "Oltivra reklamlarla desteklenir. Reklamlar yalnızca maç sonucu göründükten sonra gösterilir, soru sırasında "
        "asla gösterilmez. Ödüllü video izlemek her zaman isteğe bağlıdır ve o maç için bonus XP kazandırabilir; "
        "sıralamaları, ligleri veya maç sonuçlarını asla etkilemez.",
    ]),
    ("10. Satın almalar", [
        "Tek seferlik Reklamları Kaldır satın alımı, hesabındaki geçiş reklamlarını kaldırır. Satın almalar Google "
        "Play veya App Store tarafından, onların iade politikaları dahil kendi koşullarına göre işlenir. Satın "
        "almalar hesabına bağlıdır ve aynı hesapla başka bir cihazda geri yüklenebilir.",
    ]),
    ("11. Sorular ve içerik", [
        "Soruları doğru tutmak için çalışırız, ancak bazıları hata içerebilir veya güncelliğini yitirebilir. Bir "
        "soruyu maç ekranından bildirebilirsin. Uygulama, soruları, tasarımları ve yazılımı {operator} veya lisans "
        "verenlerine aittir; bunları yalnızca Oltivra oynamak için kullanabilirsin.",
    ]),
    ("12. Hizmetin sürekliliği", [
        "Özellikleri değiştirebilir, duraklatabilir veya sonlandırabiliriz. Bir maç güvenli şekilde devam edemezse "
        "(örneğin bir sunucu sorunundan sonra) sıralamanı etkilemeden iptal edilebilir.",
    ]),
    ("13. Hesabının sona ermesi", [
        "Hesabını istediğin zaman Ayarlar'dan veya web silme sayfamızdan silebilirsin. Giriş ortak olduğu için "
        "silme işlemi, ortak Synova hesabını katılımcı tüm ürünlerden kaldırır. Bu Koşulları ciddi veya tekrarlı "
        "şekilde ihlal eden hesapları kapatabiliriz.",
    ]),
    ("14. Sorumluluk", [
        "Oltivra olduğu gibi sunulur. Yasaların izin verdiği ölçüde {operator}, dolaylı veya sonuç olarak ortaya "
        "çıkan zararlardan ya da makul kontrolü dışındaki olayların yol açtığı zararlardan sorumlu değildir. Bu "
        "Koşullardaki hiçbir hüküm, emredici hukuk kapsamında tüketici olarak sahip olduğun hakları sınırlamaz.",
    ]),
    ("15. Değişiklikler ve uygulanacak hukuk", [
        "Bu Koşulları güncelleyebiliriz. Güncellediğimizde sürümü değiştirir ve oynamaya devam etmeden önce yeni "
        "Koşulları kabul etmeni isteriz. Bu Koşullar {law} hükümlerine tabidir; yaşadığın ülkenin emredici tüketici "
        "koruma hükümleri saklıdır.",
        "Yürürlük tarihi: {effective}.",
    ]),
]

PRIVACY_EN: list[Section] = [
    ("1. Controller", [
        "{operator}{address} is responsible for the personal data processed in Oltivra. Contact for privacy "
        "questions and requests: {contact}.",
    ]),
    ("2. Data we collect", [
        "Account: your sign-in identifier from Google, Apple or email (and the email address the provider shares), "
        "the date you accepted these documents, and your 13+ confirmation. We do not collect your date of birth.",
        "Profile: player name, chosen avatar, frame and badges, UI and question language, and notification "
        "preferences.",
        "Gameplay: matches played, your answers and their server receive time, scores, placements, XP, level, league "
        "and ranking data, mission progress and per-category statistics.",
        "Social and safety: friends and friend requests, private challenges, blocks, and reports you send or that "
        "concern you, plus moderation decisions and sanctions.",
        "Fair-play signals: answer timing patterns, malformed or excessive requests, app integrity check results, and "
        "a keyed hash of your device's push token used to limit repeated account creation. These produce an internal "
        "risk score that is never shown to other players.",
        "Device and technical: push notification token and platform, app version, and server logs that include IP "
        "address and request metadata.",
        "Purchases and rewards: store transaction identifiers and status for Remove Ads, and rewarded-video "
        "completion records. We never receive your payment card details.",
        "We do not collect precise location, contacts, photos or microphone data.",
    ]),
    ("3. Why we use it", [
        "To provide the game (account, matchmaking, live matches, progress, leaderboards, social features): "
        "performance of our contract with you.",
        "To keep matches fair and the community safe (anti-cheat, reports, moderation) and to secure the service: "
        "our legitimate interests and your safety.",
        "To show ads and verify rewarded videos and purchases: contract and, where required (for example in the EEA, "
        "UK and Switzerland), your consent for personalised ads collected through Google's consent tool.",
        "To send notifications you enabled (friend requests, challenges, reminders): your settings, which you can "
        "change at any time.",
        "To improve questions (for example calibrating difficulty from anonymous answer statistics).",
    ]),
    ("4. Who we share it with", [
        "Other players see only your public profile: player name, avatar, frame, featured badges, level, league and "
        "public achievements. They never see your email, sign-in provider or risk data.",
        "Service providers acting for us: Google Cloud and Firebase (hosting, authentication, databases, push "
        "notifications), Google AdMob (advertising and rewarded-video verification), and Google Play or Apple "
        "(purchase processing). They process data under their terms and applicable data protection agreements.",
        "Other participating Synova products using the shared sign-in receive your account identifier and "
        "question-exposure history so you are not shown the same questions repeatedly. Product-specific progress is "
        "not shared.",
        "Authorities, where the law requires it. We do not sell your personal data.",
    ]),
    ("5. Advertising", [
        "Ads are provided by Google AdMob, which may use device identifiers and similar technologies. Where required, "
        "we ask for your consent before showing personalised ads, and you can change your choice any time in "
        "Settings > Privacy & ads. If you do not consent, you may still see non-personalised ads. Buying Remove Ads "
        "stops interstitial ads.",
    ]),
    ("6. International transfers", [
        "Our primary servers are in the European Union (Google Cloud, europe-west1). Some providers may process data "
        "in other countries; in that case transfers are protected by the safeguards required by law, such as "
        "standard contractual clauses.",
    ]),
    ("7. How long we keep it", [
        "Account and profile data: while your account exists. Raw server logs: 30 days. Previous player names: a "
        "hashed reservation for 30 days after a change or deletion. Security and audit records: only as long as "
        "necessary for the purpose they serve. Match history: anonymised when you delete your account; anonymous "
        "aggregate statistics may be kept. Backups follow a documented retention period and deleted data is never "
        "restored into active systems.",
    ]),
    ("8. Deleting your account", [
        "You can delete your account in Settings or on our web deletion page, which requires a fresh sign-in. "
        "Deletion starts immediately. If you are in a live match, the match finishes or is cancelled safely first. "
        "We then delete or anonymise your profile, friends, requests, blocks, devices and notification tokens, "
        "private settings and product records, anonymise your match history, and delete your sign-in. Because the "
        "sign-in is shared, this deletes the shared Synova account across participating products.",
    ]),
    ("9. Your rights", [
        "Depending on where you live (including under the GDPR and Türkiye's KVKK), you may have the right to access, "
        "correct, delete or port your data, to object to or restrict processing, and to withdraw consent. Contact "
        "{contact}. You may also complain to your local data protection authority.",
    ]),
    ("10. Children", [
        "Oltivra is not directed at children under 13 and we do not knowingly collect their data. If you believe a "
        "child under 13 uses Oltivra, contact {contact} and we will delete the account.",
    ]),
    ("11. Security", [
        "Data is encrypted in transit, access is limited to authorised staff with multi-factor authentication, and "
        "sensitive identifiers are stored as keyed hashes where possible.",
    ]),
    ("12. Changes", [
        "When we change this policy we update its version and ask you to review it in the app before you continue.",
        "Effective date: {effective}.",
    ]),
]

PRIVACY_TR: list[Section] = [
    ("1. Veri sorumlusu", [
        "Oltivra'da işlenen kişisel verilerden {operator}{address} sorumludur. Gizlilikle ilgili soruların ve "
        "talepler için iletişim: {contact}.",
    ]),
    ("2. Topladığımız veriler", [
        "Hesap: Google, Apple veya e-posta giriş kimliğin (ve sağlayıcının paylaştığı e-posta adresi), bu belgeleri "
        "kabul ettiğin tarih ve 13+ onayın. Doğum tarihini toplamayız.",
        "Profil: oyuncu adı, seçtiğin avatar, çerçeve ve rozetler, arayüz ve soru dili ile bildirim tercihleri.",
        "Oyun: oynadığın maçlar, cevapların ve sunucuya ulaşma zamanları, puanlar, sıralar, XP, seviye, lig ve "
        "sıralama verileri, görev ilerlemesi ve kategori bazlı istatistikler.",
        "Sosyal ve güvenlik: arkadaşlar ve arkadaşlık istekleri, özel meydan okumalar, engellemeler, gönderdiğin veya "
        "seninle ilgili bildirimler ile moderasyon kararları ve yaptırımlar.",
        "Adil oyun sinyalleri: cevap süresi örüntüleri, hatalı veya aşırı istekler, uygulama bütünlüğü kontrol "
        "sonuçları ve tekrarlı hesap açmayı sınırlamak için cihazının bildirim anahtarının anahtarlı özeti. Bunlar "
        "diğer oyunculara asla gösterilmeyen dahili bir risk puanı oluşturur.",
        "Cihaz ve teknik: bildirim anahtarı ve platform, uygulama sürümü ile IP adresi ve istek bilgilerini içeren "
        "sunucu kayıtları.",
        "Satın almalar ve ödüller: Reklamları Kaldır için mağaza işlem kimlikleri ve durumları, ödüllü video "
        "tamamlama kayıtları. Kart bilgilerini asla almayız.",
        "Hassas konum, kişiler, fotoğraflar veya mikrofon verisi toplamayız.",
    ]),
    ("3. Verileri neden kullanıyoruz", [
        "Oyunu sunmak için (hesap, eşleştirme, canlı maçlar, ilerleme, sıralamalar, sosyal özellikler): seninle "
        "yaptığımız sözleşmenin ifası.",
        "Maçları adil ve topluluğu güvenli tutmak (hile önleme, bildirimler, moderasyon) ve hizmeti korumak için: "
        "meşru menfaatlerimiz ve senin güvenliğin.",
        "Reklam göstermek, ödüllü videoları ve satın almaları doğrulamak için: sözleşme ve gerektiğinde (örneğin AEA, "
        "Birleşik Krallık ve İsviçre'de) Google'ın izin aracıyla alınan kişiselleştirilmiş reklam iznin.",
        "Açtığın bildirimleri (arkadaşlık istekleri, meydan okumalar, hatırlatmalar) göndermek için: istediğin zaman "
        "değiştirebileceğin ayarların.",
        "Soruları geliştirmek için (örneğin zorluğu anonim cevap istatistiklerinden ayarlamak).",
    ]),
    ("4. Verileri kimlerle paylaşıyoruz", [
        "Diğer oyuncular yalnızca herkese açık profilini görür: oyuncu adı, avatar, çerçeve, öne çıkan rozetler, "
        "seviye, lig ve herkese açık başarımlar. E-postanı, giriş sağlayıcını veya risk verilerini asla görmezler.",
        "Bizim adımıza çalışan hizmet sağlayıcılar: Google Cloud ve Firebase (barındırma, kimlik doğrulama, "
        "veritabanları, bildirimler), Google AdMob (reklamlar ve ödüllü video doğrulaması) ve Google Play veya "
        "Apple (satın alma işlemleri). Verileri kendi koşulları ve ilgili veri koruma sözleşmeleri kapsamında "
        "işlerler.",
        "Ortak girişi kullanan diğer Synova ürünleri, aynı soruları tekrar tekrar görmemen için hesap kimliğini ve "
        "soru görme geçmişini alır. Ürüne özel ilerleme paylaşılmaz.",
        "Yasanın gerektirdiği durumlarda yetkili makamlar. Kişisel verilerini satmayız.",
    ]),
    ("5. Reklamlar", [
        "Reklamlar, cihaz tanımlayıcıları ve benzeri teknolojileri kullanabilen Google AdMob tarafından sağlanır. "
        "Gerektiğinde kişiselleştirilmiş reklam göstermeden önce iznini isteriz; tercihini istediğin zaman Ayarlar > "
        "Gizlilik ve reklamlar bölümünden değiştirebilirsin. İzin vermezsen kişiselleştirilmemiş reklamlar görmeye "
        "devam edebilirsin. Reklamları Kaldır satın alımı geçiş reklamlarını durdurur.",
    ]),
    ("6. Yurt dışına aktarım", [
        "Ana sunucularımız Avrupa Birliği'ndedir (Google Cloud, europe-west1). Bazı sağlayıcılar verileri başka "
        "ülkelerde işleyebilir; bu durumda aktarımlar, standart sözleşme hükümleri gibi yasanın gerektirdiği "
        "güvencelerle korunur.",
    ]),
    ("7. Ne kadar süre saklıyoruz", [
        "Hesap ve profil verileri: hesabın var olduğu sürece. Ham sunucu kayıtları: 30 gün. Eski oyuncu adları: ad "
        "değişikliği veya silme sonrasında 30 gün boyunca özetlenmiş bir ayırma kaydı. Güvenlik ve denetim kayıtları: "
        "yalnızca amaçları için gerekli olduğu sürece. Maç geçmişi: hesabını sildiğinde anonimleştirilir; anonim "
        "toplu istatistikler saklanabilir. Yedekler belgelenmiş bir saklama süresine tabidir ve silinen veriler "
        "aktif sistemlere asla geri yüklenmez.",
    ]),
    ("8. Hesabını silmek", [
        "Hesabını Ayarlar'dan veya yeniden giriş gerektiren web silme sayfamızdan silebilirsin. Silme hemen başlar. "
        "Canlı bir maçtaysan önce maç güvenli şekilde biter veya iptal edilir. Ardından profilini, arkadaşlarını, "
        "isteklerini, engellemelerini, cihazlarını ve bildirim anahtarlarını, özel ayarlarını ve ürün kayıtlarını "
        "siler veya anonimleştirir, maç geçmişini anonimleştirir ve girişini sileriz. Giriş ortak olduğundan bu "
        "işlem ortak Synova hesabını katılımcı tüm ürünlerden siler.",
    ]),
    ("9. Hakların", [
        "Yaşadığın yere bağlı olarak (GDPR ve KVKK dahil) verilerine erişme, düzeltme, silme ve taşıma, işlemeye "
        "itiraz etme veya kısıtlama ve iznini geri çekme hakların olabilir. {contact} adresine yaz. Ayrıca yerel veri "
        "koruma kurumuna (Türkiye'de Kişisel Verileri Koruma Kurumu) şikâyette bulunabilirsin.",
    ]),
    ("10. Çocuklar", [
        "Oltivra 13 yaşından küçük çocuklara yönelik değildir ve onların verilerini bilerek toplamayız. 13 yaşından "
        "küçük bir çocuğun Oltivra kullandığını düşünüyorsan {contact} adresine yaz; hesabı sileriz.",
    ]),
    ("11. Güvenlik", [
        "Veriler aktarım sırasında şifrelenir, erişim çok faktörlü kimlik doğrulama kullanan yetkili personelle "
        "sınırlıdır ve hassas tanımlayıcılar mümkün olduğunda anahtarlı özet olarak saklanır.",
    ]),
    ("12. Değişiklikler", [
        "Bu politikayı değiştirdiğimizde sürümünü günceller ve devam etmeden önce uygulamada incelemeni isteriz.",
        "Yürürlük tarihi: {effective}.",
    ]),
]

TITLES = {
    "terms": {"en": "Terms of Service", "tr": "Kullanım Koşulları"},
    "privacy": {"en": "Privacy Policy", "tr": "Gizlilik Politikası"},
}

DOCUMENTS: dict[str, dict[str, list[Section]]] = {
    "terms": {"en": TERMS_EN, "tr": TERMS_TR},
    "privacy": {"en": PRIVACY_EN, "tr": PRIVACY_TR},
}


@dataclass(frozen=True)
class LegalIdentity:
    operator: str
    contact: str
    address: str
    law: str
    effective: str


def render(doc: str, language: str, identity: LegalIdentity) -> tuple[str, list[dict[str, object]]]:
    """Title and filled sections for ``doc`` in ``language`` (falls back to English)."""
    lang = language if language in DOCUMENTS[doc] else "en"
    values = {
        "operator": identity.operator,
        "contact": identity.contact,
        "address": f", {identity.address}" if identity.address else "",
        "law": identity.law,
        "effective": identity.effective,
    }
    sections = [{"heading": heading, "paragraphs": [p.format(**values) for p in paragraphs]}
                for heading, paragraphs in DOCUMENTS[doc][lang]]
    return TITLES[doc][lang], sections
