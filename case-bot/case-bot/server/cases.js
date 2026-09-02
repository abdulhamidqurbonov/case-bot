// Keyslar katalogi.
//
// RASM QO'SHISH HAQIDA: har bir sovg'a va keys "icon" maydoniga ega (pistol/smg/rifle/
// shotgun/sniper/knife). Frontend bu qiymatni /assets/weapons/{icon}.png fayliga bog'laydi —
// batafsili: public/assets/weapons/README.txt. Faylni topa olmasa, avtomatik ravishda
// rangli vektor zaxira ko'rinishini chizadi (hech narsa sinmaydi).
//
// TASODIFIYLIK HAQIDA: qaysi sovg'a tushishi har bir ochishda serverda Math.random() orqali,
// pastdagi "weight" ustunlari asosida hisoblanadi (pickPrize funksiyasi, shu fayl oxirida).
// Bu haqiqiy tasodifiy tanlov — natija oldindan belgilanmagan. Ekrandagi aylanuvchi
// "reel" faqat SERVER ALLAQACHON TANLAGAN natijani vizual ko'rsatish uchun; pedestal/ramka —
// shunchaki dizayn elementi (har qanday tasodifiy natija o'sha ramkaga tushib ko'rsatiladi),
// natija oldindan "qotirilgan" emas.

const CASES = [
  {
    id: 'daily_free',
    name: "Kunlik bepul keys",
    category: ['barchasi'],
    price: 0,
    theme: 'green',
    displayIcon: 'pistol',
    displayRarity: 'common',
    tagline: "Har kuni bir marta — hech narsa to'lamasdan kichik sovg'a yutib oling.",
    prizes: [
      { name: 'Pistolet — Sahro', icon: 'pistol', rarity: 'common', value: 5, weight: 45 },
      { name: 'SMG — Ko\u2018k To\u2018lqin', icon: 'smg', rarity: 'uncommon', value: 15, weight: 27 },
      { name: 'Mildiq — Tun Soyasi', icon: 'rifle', rarity: 'rare', value: 25, weight: 16 },
      { name: 'Drobovik — Qizil Zarba', icon: 'shotgun', rarity: 'epic', value: 50, weight: 9 },
      { name: 'Snayper — Muz Yulduz', icon: 'sniper', rarity: 'legendary', value: 150, weight: 3 },
    ],
  },
  {
    id: 'budget',
    name: 'Byudjet',
    category: ['barchasi', 'byudjet'],
    price: 15000,
    theme: 'khaki',
    displayIcon: 'rifle',
    displayRarity: 'uncommon',
    tagline: "Kichik xavflarni yoqtiradiganlar uchun — arzon quti, katta potensial.",
    prizes: [
      { name: 'SMG — Qum Bo\u2018roni', icon: 'smg', rarity: 'uncommon', value: 15, weight: 34 },
      { name: 'Mildiq — Ko\u2018k Alanga', icon: 'rifle', rarity: 'rare', value: 25, weight: 26 },
      { name: 'Drobovik — Neon Zarba', icon: 'shotgun', rarity: 'epic', value: 50, weight: 20 },
      { name: 'Snayper — Kumush Yulduz', icon: 'sniper', rarity: 'legendary', value: 150, weight: 14 },
      { name: 'Pichoq — Oltin Tola', icon: 'knife', rarity: 'mythic', value: 500, weight: 5 },
      { name: 'Pichoq — Kosmik Parcha', icon: 'knife', rarity: 'mythic', value: 2000, weight: 1 },
    ],
  },
  {
    id: 'popular',
    name: 'Mashhur',
    category: ['barchasi', 'byudjet'],
    price: 35000,
    theme: 'blue',
    displayIcon: 'smg',
    displayRarity: 'rare',
    tagline: "Eng ko'p ochilayotgan keys — muvozanatli imkoniyatlar.",
    prizes: [
      { name: 'Drobovik — Zumrad Olov', icon: 'shotgun', rarity: 'epic', value: 50, weight: 30 },
      { name: 'Snayper — Alanga Ko\u2018zi', icon: 'sniper', rarity: 'legendary', value: 150, weight: 28 },
      { name: 'Pichoq — Feniks Qanoti', icon: 'knife', rarity: 'mythic', value: 300, weight: 18 },
      { name: 'Pichoq — Qirol Tangasi', icon: 'knife', rarity: 'mythic', value: 500, weight: 14 },
      { name: 'Pichoq — Yulduz Yog\u2018dusi', icon: 'knife', rarity: 'mythic', value: 2000, weight: 8 },
      { name: 'Pichoq — Marvarid Zarbasi', icon: 'knife', rarity: 'mythic', value: 5000, weight: 2 },
    ],
  },
  {
    id: 'starlight',
    name: 'Yulduzli',
    category: ['barchasi', 'tematik'],
    price: 75000,
    theme: 'purple',
    displayIcon: 'sniper',
    displayRarity: 'epic',
    tagline: "Yorqin va nodir sovg'alar ko'proq uchraydi.",
    prizes: [
      { name: 'Snayper — Kumush Chaqmoq', icon: 'sniper', rarity: 'legendary', value: 150, weight: 26 },
      { name: 'Pichoq — Feniks Alangasi', icon: 'knife', rarity: 'mythic', value: 300, weight: 24 },
      { name: 'Pichoq — Qirollik Muhri', icon: 'knife', rarity: 'mythic', value: 500, weight: 22 },
      { name: 'Pichoq — Kosmik To\u2018lqin', icon: 'knife', rarity: 'mythic', value: 2000, weight: 16 },
      { name: 'Pichoq — Yulduz Yomg\u2018iri', icon: 'knife', rarity: 'mythic', value: 5000, weight: 9 },
      { name: 'Pichoq — Galaktika Nafasi', icon: 'knife', rarity: 'mythic', value: 15000, weight: 3 },
    ],
  },
  {
    id: 'vip',
    name: 'VIP',
    category: ['barchasi', 'premium'],
    price: 150000,
    theme: 'gold',
    displayIcon: 'shotgun',
    displayRarity: 'legendary',
    tagline: "Yuqori qiymatli sovg'alar ehtimoli sezilarli oshirilgan.",
    prizes: [
      { name: 'Pichoq — Oltin Qanot', icon: 'knife', rarity: 'mythic', value: 300, weight: 20 },
      { name: 'Pichoq — Qirol Toji', icon: 'knife', rarity: 'mythic', value: 500, weight: 24 },
      { name: 'Pichoq — Feniks Olovi', icon: 'knife', rarity: 'mythic', value: 2000, weight: 26 },
      { name: 'Pichoq — Kumush Bo\u2018ron', icon: 'knife', rarity: 'mythic', value: 5000, weight: 18 },
      { name: 'Pichoq — Kosmik Sirlar', icon: 'knife', rarity: 'mythic', value: 15000, weight: 9 },
      { name: 'Pichoq — Afsonaviy Zarba', icon: 'knife', rarity: 'mythic', value: 40000, weight: 3 },
    ],
  },
  {
    id: 'jackpot',
    name: 'Jackpot',
    category: ['barchasi', 'premium'],
    price: 300000,
    theme: 'red',
    displayIcon: 'knife',
    displayRarity: 'mythic',
    tagline: "Eng qimmat keys — eng katta yutuqlar shu yerda.",
    prizes: [
      { name: 'Pichoq — Qonli Oy', icon: 'knife', rarity: 'mythic', value: 500, weight: 16 },
      { name: 'Pichoq — Alanga Qirg\u2018ini', icon: 'knife', rarity: 'mythic', value: 2000, weight: 26 },
      { name: 'Pichoq — Zumrad Bo\u2018roni', icon: 'knife', rarity: 'mythic', value: 5000, weight: 28 },
      { name: 'Pichoq — Kosmik Halokat', icon: 'knife', rarity: 'mythic', value: 15000, weight: 20 },
      { name: 'Pichoq — Afsona Nafasi', icon: 'knife', rarity: 'mythic', value: 40000, weight: 8 },
      { name: 'Pichoq — Yulduzlar Yaratuvchisi', icon: 'knife', rarity: 'mythic', value: 100000, weight: 2 },
    ],
  },
];

const CATEGORIES = [
  { id: 'barchasi', label: 'Hammasi' },
  { id: 'byudjet', label: 'Byudjet' },
  { id: 'tematik', label: 'Tematik' },
  { id: 'premium', label: 'Premium' },
];

function getCase(id) {
  return CASES.find((c) => c.id === id) || null;
}

// Haqiqiy tasodifiy tanlov: Math.random() natijasi hech qayerda oldindan yozilmagan yoki
// foydalanuvchi/keysga qarab "moslashtirilmagan" — har bir chaqiruvda mustaqil, adolatli tanlov.
function pickPrize(caseObj) {
  const pool = caseObj.prizes;
  const totalWeight = pool.reduce((sum, p) => sum + p.weight, 0);
  let rand = Math.random() * totalWeight;
  for (const prize of pool) {
    if (rand < prize.weight) return prize;
    rand -= prize.weight;
  }
  return pool[0];
}

// Frontendga yuboriladigan xavfsiz (weight'siz) ro'yxat.
function publicCaseList() {
  return CASES.map((c) => ({
    id: c.id,
    name: c.name,
    category: c.category,
    price: c.price,
    theme: c.theme,
    displayIcon: c.displayIcon,
    displayRarity: c.displayRarity,
    tagline: c.tagline,
    preview: [...c.prizes].sort((a, b) => b.value - a.value).slice(0, 3)
      .map((p) => ({ name: p.name, icon: p.icon, rarity: p.rarity, value: p.value })),
    topValue: Math.max(...c.prizes.map((p) => p.value)),
  }));
}

module.exports = { CASES, CATEGORIES, getCase, pickPrize, publicCaseList };
