// Strings for the onboarding package; keys are prefixed 'onboarding.'.
const Map<String, Map<String, String>> onboardingStrings = {
  'en': {
    // Shared
    'onboarding.step': 'Step {n} of {total} · Account setup',
    'onboarding.progress_label': 'Account setup progress',

    // Launch
    'onboarding.launch.tagline': 'Think fast. Rise higher.',
    'onboarding.launch.footer': 'LIVE TRIVIA DUELS',
    'onboarding.launch.get_started': 'Get started',
    'onboarding.launch.have_account': 'I already have an account',
    'onboarding.launch.sign_out': 'Sign out',

    // Age gate
    'onboarding.age.title': 'Age Gate',
    'onboarding.age.badge': 'FAIR PLAY',
    'onboarding.age.hero_title': 'Age check',
    'onboarding.age.hero_body': 'One tap and you’re ready for live multiplayer battles.',
    'onboarding.age.heading': 'Before you play',
    'onboarding.age.body': 'Oltivra is for players aged 13 and over.',
    'onboarding.age.confirm': 'I confirm I am 13 or older.',
    'onboarding.age.confirm_hint': 'Required to join live battles and public leaderboards.',
    'onboarding.age.privacy': 'No birthday or personal data needed. We only keep that you confirmed.',
    'onboarding.age.under_13': 'I’m under 13',
    'onboarding.age.blocked_title': 'Oltivra isn’t available yet',
    'onboarding.age.blocked_body':
        'Oltivra is made for players aged 13 and over, so we can’t create an account for you right now. '
            'Thanks for your interest — we’d love to see you when you’re older!',
    'onboarding.age.blocked_back': 'Go back',

    // Terms
    'onboarding.terms.title': 'Legal Consent',
    'onboarding.terms.heading': 'A quick agreement',
    'onboarding.terms.body': 'Before joining live battles, please review and accept these two documents.',
    'onboarding.terms.tos': 'Terms of Service',
    'onboarding.terms.tos_sub': 'Match rules & fair play standards',
    'onboarding.terms.privacy': 'Privacy Policy',
    'onboarding.terms.privacy_sub': 'What we store and how we protect it',
    'onboarding.terms.agree_tos': 'I agree to the Terms of Service.',
    'onboarding.terms.agree_privacy': 'I agree to the Privacy Policy.',
    'onboarding.terms.required': 'Both are required to play live battles and appear on leaderboards.',
    'onboarding.terms.read': 'Read {doc}',
    'onboarding.terms.continue': 'Agree and continue',
    'onboarding.terms.footer': 'No marketing emails. Ads never block your games.',
    'onboarding.terms.version': 'Version {v}',
    'onboarding.terms.tos_text':
        'Summary\n\n'
            '• Oltivra is a live trivia game for players aged 13 and over.\n'
            '• Play fair: no cheating, automation, collusion or exploiting bugs.\n'
            '• Choose a respectful player name. Offensive or impersonating names may be changed.\n'
            '• Be kind to other players. Harassment, hate and spam lead to restrictions.\n'
            '• Scores, rankings and rewards are decided by our servers and may be corrected if something goes wrong.\n'
            '• Purchases such as removing ads follow your app store’s terms.\n'
            '• You can delete your account at any time from Settings.',
    'onboarding.terms.privacy_text':
        'Summary\n\n'
            '• We store your account ID, player name, avatar, language preferences and game progress.\n'
            '• We do not ask for your birthday, phone number, address or photos.\n'
            '• We record that you confirmed you are 13+ and accepted these documents, with the date and version.\n'
            '• Match data is used to run fair games, calculate rankings and keep questions fresh.\n'
            '• Ads, if shown, follow the choices in Privacy & ads settings.\n'
            '• You can request deletion of your account and personal data at any time.',

    // Sign in
    'onboarding.signin.title': 'Sign In',
    'onboarding.signin.heading': 'Ready to play?',
    'onboarding.signin.body': 'Sign in to join live battles and keep your progress.',
    'onboarding.signin.google': 'Continue with Google',
    'onboarding.signin.apple': 'Continue with Apple',
    'onboarding.signin.email': 'Continue with email',
    'onboarding.signin.safe': 'Safe & instant sync',
    'onboarding.signin.legal': 'By continuing, you confirm you agreed to our Terms of Service and Privacy Policy.',
    'onboarding.email.title_create': 'Create your account',
    'onboarding.email.title_signin': 'Sign in with email',
    'onboarding.email.email': 'Email',
    'onboarding.email.password': 'Password',
    'onboarding.email.show_password': 'Show password',
    'onboarding.email.hide_password': 'Hide password',
    'onboarding.email.submit_create': 'Create account',
    'onboarding.email.submit_signin': 'Sign in',
    'onboarding.email.toggle_to_signin': 'Already have an account? Sign in',
    'onboarding.email.toggle_to_create': 'New here? Create an account',
    'onboarding.email.invalid_email': 'Enter a valid email address.',
    'onboarding.email.short_password': 'Use at least 6 characters.',
    'onboarding.email.error.wrong_credentials': 'Email or password is incorrect.',
    'onboarding.email.error.in_use': 'An account with this email already exists. Try signing in.',
    'onboarding.email.error.weak_password': 'Choose a stronger password.',
    'onboarding.email.error.too_many': 'Too many attempts. Please wait a moment and try again.',

    // Choose name
    'onboarding.name.title': 'Player Name',
    'onboarding.name.heading': 'Choose your player name',
    'onboarding.name.heading_rename': 'Choose a new player name',
    'onboarding.name.body': 'This is how other players will see you.',
    'onboarding.name.body_forced': 'Your current name can’t be used any more. Pick a new one to keep playing.',
    'onboarding.name.hint': 'Player name',
    'onboarding.name.rules': '3–16 characters · letters, numbers, and _ only',
    'onboarding.name.checking': 'Checking…',
    'onboarding.name.available': 'Name available',
    'onboarding.name.taken': 'That name is already taken',
    'onboarding.name.format': 'Use 3–16 letters, numbers or _',
    'onboarding.name.reserved': 'That name is reserved',
    'onboarding.name.profanity': 'That name isn’t allowed',
    'onboarding.name.invalid': 'That name isn’t allowed',
    'onboarding.name.cooldown': 'You can change your name again on {date}',
    'onboarding.name.cooldown_generic': 'You can change your name again later',
    'onboarding.name.roll_title': 'Feeling spontaneous?',
    'onboarding.name.roll_body': 'Tap to roll a fun random name',
    'onboarding.name.roll': 'Roll',
    'onboarding.name.change_rule': 'You can change this once every 30 days',

    // Avatar
    'onboarding.avatar.title': 'Avatar Selection',
    'onboarding.avatar.badge': 'EXPRESS YOUR VIBE',
    'onboarding.avatar.heading': 'Pick your avatar',
    'onboarding.avatar.body': 'Choose how you appear in live battles and on leaderboards.',
    'onboarding.avatar.helper': 'You can change this later.',
    'onboarding.avatar.start': 'Start playing',
    'onboarding.avatar.save': 'Save avatar',
    'onboarding.avatar.option': 'Avatar {n}',
    'onboarding.avatar.empty': 'No avatars available right now',

    // Guide
    'onboarding.guide.title': 'Game Guide',
    'onboarding.guide.eyebrow': 'HOW IT WORKS',
    'onboarding.guide.heading': 'Two ways to rise',
    'onboarding.guide.body': 'Master the live quiz arena in two fast formats.',
    'onboarding.guide.quick_tag': 'Head-to-head sprint',
    'onboarding.guide.quick_summary': '{players} players · {questions} questions · first correct answer scores.',
    'onboarding.guide.quick_speed': 'Faster answers earn more — up to {max} points in {seconds} seconds.',
    'onboarding.guide.quick_wrong': 'A wrong answer costs {wrong} points and locks you for the round.',
    'onboarding.guide.quick_skip': 'Not sure? Skipping costs {skip} points.',
    'onboarding.guide.quick_skip_free': 'Not sure? Skipping a question costs nothing.',
    'onboarding.guide.survival_tag': 'Last standing',
    'onboarding.guide.survival_summary': '{players} players · a wrong or missing answer eliminates you.',
    'onboarding.guide.survival_timer': '{seconds} seconds per question. Last player standing wins.',
    'onboarding.guide.survival_note': 'High stakes, pure endurance',
    'onboarding.guide.footer': 'Everyone in a match gets the same question at the same moment.',
    'onboarding.guide.play': 'Let’s play',
    'onboarding.guide.close': 'Close guide',
  },
  'tr': {
    // Shared
    'onboarding.step': 'Adım {n}/{total} · Hesap kurulumu',
    'onboarding.progress_label': 'Hesap kurulumu ilerlemesi',

    // Launch
    'onboarding.launch.tagline': 'Hızlı düşün. Yükseğe çık.',
    'onboarding.launch.footer': 'CANLI BİLGİ DÜELLOLARI',
    'onboarding.launch.get_started': 'Hadi başlayalım',
    'onboarding.launch.have_account': 'Zaten bir hesabım var',
    'onboarding.launch.sign_out': 'Çıkış yap',

    // Age gate
    'onboarding.age.title': 'Yaş Onayı',
    'onboarding.age.badge': 'ADİL OYUN',
    'onboarding.age.hero_title': 'Yaş kontrolü',
    'onboarding.age.hero_body': 'Tek dokunuşla canlı çok oyunculu düellolara hazırsın.',
    'onboarding.age.heading': 'Oynamadan önce',
    'onboarding.age.body': 'Oltivra 13 yaş ve üzeri oyuncular içindir.',
    'onboarding.age.confirm': '13 yaşında veya daha büyük olduğumu onaylıyorum.',
    'onboarding.age.confirm_hint': 'Canlı düellolara ve herkese açık sıralamalara katılmak için gerekli.',
    'onboarding.age.privacy': 'Doğum tarihi ya da kişisel bilgi gerekmez. Sadece onay verdiğini saklarız.',
    'onboarding.age.under_13': '13 yaşından küçüğüm',
    'onboarding.age.blocked_title': 'Oltivra henüz sana uygun değil',
    'onboarding.age.blocked_body':
        'Oltivra 13 yaş ve üzeri oyuncular için tasarlandı, bu yüzden şu an senin için hesap oluşturamıyoruz. '
            'İlgin için teşekkürler — biraz büyüdüğünde seni aramızda görmek isteriz!',
    'onboarding.age.blocked_back': 'Geri dön',

    // Terms
    'onboarding.terms.title': 'Yasal Onay',
    'onboarding.terms.heading': 'Kısa bir anlaşma',
    'onboarding.terms.body': 'Canlı düellolara katılmadan önce lütfen bu iki belgeyi incele ve kabul et.',
    'onboarding.terms.tos': 'Kullanım Koşulları',
    'onboarding.terms.tos_sub': 'Maç kuralları ve adil oyun standartları',
    'onboarding.terms.privacy': 'Gizlilik Politikası',
    'onboarding.terms.privacy_sub': 'Neleri sakladığımız ve nasıl koruduğumuz',
    'onboarding.terms.agree_tos': 'Kullanım Koşulları’nı kabul ediyorum.',
    'onboarding.terms.agree_privacy': 'Gizlilik Politikası’nı kabul ediyorum.',
    'onboarding.terms.required': 'Canlı düellolarda oynamak ve sıralamalarda yer almak için ikisi de gerekli.',
    'onboarding.terms.read': '{doc} metnini oku',
    'onboarding.terms.continue': 'Kabul et ve devam et',
    'onboarding.terms.footer': 'Pazarlama e-postası yok. Reklamlar oyununu asla engellemez.',
    'onboarding.terms.version': 'Sürüm {v}',
    'onboarding.terms.tos_text':
        'Özet\n\n'
            '• Oltivra, 13 yaş ve üzeri oyuncular için canlı bir bilgi yarışması oyunudur.\n'
            '• Adil oyna: hile, otomasyon, iş birliği ya da hata istismarı yasaktır.\n'
            '• Saygılı bir oyuncu adı seç. Saldırgan veya başkasını taklit eden adlar değiştirilebilir.\n'
            '• Diğer oyunculara nazik ol. Taciz, nefret söylemi ve spam kısıtlamaya yol açar.\n'
            '• Puanlar, sıralamalar ve ödüller sunucularımız tarafından belirlenir; bir hata olursa düzeltilebilir.\n'
            '• Reklamları kaldırma gibi satın almalar uygulama mağazanın koşullarına tabidir.\n'
            '• Hesabını istediğin zaman Ayarlar’dan silebilirsin.',
    'onboarding.terms.privacy_text':
        'Özet\n\n'
            '• Hesap kimliğini, oyuncu adını, avatarını, dil tercihlerini ve oyun ilerlemeni saklarız.\n'
            '• Doğum tarihi, telefon numarası, adres ya da fotoğraf istemeyiz.\n'
            '• 13 yaş onayını ve bu belgeleri kabul ettiğini tarih ve sürümüyle kaydederiz.\n'
            '• Maç verileri adil oyunlar yürütmek, sıralamaları hesaplamak ve soruları taze tutmak için kullanılır.\n'
            '• Reklam gösterilirse Gizlilik ve reklam ayarlarındaki seçimlerine uyulur.\n'
            '• Hesabının ve kişisel verilerinin silinmesini istediğin zaman talep edebilirsin.',

    // Sign in
    'onboarding.signin.title': 'Giriş Yap',
    'onboarding.signin.heading': 'Oynamaya hazır mısın?',
    'onboarding.signin.body': 'Canlı düellolara katılmak ve ilerlemeni korumak için giriş yap.',
    'onboarding.signin.google': 'Google ile devam et',
    'onboarding.signin.apple': 'Apple ile devam et',
    'onboarding.signin.email': 'E-posta ile devam et',
    'onboarding.signin.safe': 'Güvenli ve anında senkron',
    'onboarding.signin.legal':
        'Devam ederek Kullanım Koşulları ve Gizlilik Politikası’nı kabul ettiğini onaylarsın.',
    'onboarding.email.title_create': 'Hesabını oluştur',
    'onboarding.email.title_signin': 'E-posta ile giriş yap',
    'onboarding.email.email': 'E-posta',
    'onboarding.email.password': 'Şifre',
    'onboarding.email.show_password': 'Şifreyi göster',
    'onboarding.email.hide_password': 'Şifreyi gizle',
    'onboarding.email.submit_create': 'Hesap oluştur',
    'onboarding.email.submit_signin': 'Giriş yap',
    'onboarding.email.toggle_to_signin': 'Zaten hesabın var mı? Giriş yap',
    'onboarding.email.toggle_to_create': 'Yeni misin? Hesap oluştur',
    'onboarding.email.invalid_email': 'Geçerli bir e-posta adresi gir.',
    'onboarding.email.short_password': 'En az 6 karakter kullan.',
    'onboarding.email.error.wrong_credentials': 'E-posta veya şifre hatalı.',
    'onboarding.email.error.in_use': 'Bu e-postayla zaten bir hesap var. Giriş yapmayı dene.',
    'onboarding.email.error.weak_password': 'Daha güçlü bir şifre seç.',
    'onboarding.email.error.too_many': 'Çok fazla deneme yapıldı. Biraz bekleyip tekrar dene.',

    // Choose name
    'onboarding.name.title': 'Oyuncu Adı',
    'onboarding.name.heading': 'Oyuncu adını seç',
    'onboarding.name.heading_rename': 'Yeni bir oyuncu adı seç',
    'onboarding.name.body': 'Diğer oyuncular seni bu adla görecek.',
    'onboarding.name.body_forced': 'Mevcut adın artık kullanılamıyor. Oynamaya devam etmek için yeni bir ad seç.',
    'onboarding.name.hint': 'Oyuncu adı',
    'onboarding.name.rules': '3–16 karakter · yalnızca harf, rakam ve _',
    'onboarding.name.checking': 'Kontrol ediliyor…',
    'onboarding.name.available': 'Bu ad kullanılabilir',
    'onboarding.name.taken': 'Bu ad zaten alınmış',
    'onboarding.name.format': '3–16 harf, rakam veya _ kullan',
    'onboarding.name.reserved': 'Bu ad ayrılmış',
    'onboarding.name.profanity': 'Bu ada izin verilmiyor',
    'onboarding.name.invalid': 'Bu ada izin verilmiyor',
    'onboarding.name.cooldown': 'Adını {date} tarihinde tekrar değiştirebilirsin',
    'onboarding.name.cooldown_generic': 'Adını daha sonra tekrar değiştirebilirsin',
    'onboarding.name.roll_title': 'Canın sürpriz mi istiyor?',
    'onboarding.name.roll_body': 'Rastgele eğlenceli bir ad için dokun',
    'onboarding.name.roll': 'Zar at',
    'onboarding.name.change_rule': 'Bunu 30 günde bir değiştirebilirsin',

    // Avatar
    'onboarding.avatar.title': 'Avatar Seçimi',
    'onboarding.avatar.badge': 'TARZINI GÖSTER',
    'onboarding.avatar.heading': 'Avatarını seç',
    'onboarding.avatar.body': 'Canlı düellolarda ve sıralamalarda nasıl görüneceğini seç.',
    'onboarding.avatar.helper': 'Bunu daha sonra değiştirebilirsin.',
    'onboarding.avatar.start': 'Oynamaya başla',
    'onboarding.avatar.save': 'Avatarı kaydet',
    'onboarding.avatar.option': 'Avatar {n}',
    'onboarding.avatar.empty': 'Şu anda kullanılabilir avatar yok',

    // Guide
    'onboarding.guide.title': 'Oyun Rehberi',
    'onboarding.guide.eyebrow': 'NASIL OYNANIR',
    'onboarding.guide.heading': 'Yükselmenin iki yolu',
    'onboarding.guide.body': 'Canlı bilgi arenasında iki hızlı formatta ustalaş.',
    'onboarding.guide.quick_tag': 'Kafa kafaya sprint',
    'onboarding.guide.quick_summary': '{players} oyuncu · {questions} soru · ilk doğru cevap puanı alır.',
    'onboarding.guide.quick_speed': 'Ne kadar hızlı cevaplarsan o kadar çok puan: {seconds} saniyede en fazla {max} puan.',
    'onboarding.guide.quick_wrong': 'Yanlış cevap {wrong} puan kaybettirir ve seni o tur için kilitler.',
    'onboarding.guide.quick_skip': 'Emin değil misin? Cevap vermemenin cezası {skip} puan.',
    'onboarding.guide.quick_skip_free': 'Emin değil misin? Soruyu boş geçmenin cezası yok.',
    'onboarding.guide.survival_tag': 'Son kalan kazanır',
    'onboarding.guide.survival_summary': '{players} oyuncu · yanlış ya da boş cevap seni eler.',
    'onboarding.guide.survival_timer': 'Soru başına {seconds} saniye. Ayakta kalan son oyuncu kazanır.',
    'onboarding.guide.survival_note': 'Yüksek risk, saf dayanıklılık',
    'onboarding.guide.footer': 'Bir maçtaki herkes aynı soruyu aynı anda alır.',
    'onboarding.guide.play': 'Hadi oynayalım',
    'onboarding.guide.close': 'Rehberi kapat',
  },
};
