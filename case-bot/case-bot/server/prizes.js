// Har bir sovg'a: name, value (ichki ball/reyting uchun), weight (qancha ehtimoli bor — katta son = ko'proq tushadi)
const FREE_PRIZES = [
  { name: '🎈 Balloon', value: 5, weight: 40 },
  { name: '🧸 Teddy Bear', value: 15, weight: 25 },
  { name: '💐 Bouquet', value: 25, weight: 18 },
  { name: '🎁 Gift Box', value: 50, weight: 10 },
  { name: '💎 Gem', value: 150, weight: 5 },
  { name: '👑 Golden Crown', value: 500, weight: 2 },
];

// Premium case'da yuqori qiymatli sovg'a ehtimoli oshiriladi
const PREMIUM_PRIZES = [
  { name: '🧸 Teddy Bear', value: 15, weight: 20 },
  { name: '💐 Bouquet', value: 25, weight: 22 },
  { name: '🎁 Gift Box', value: 50, weight: 25 },
  { name: '💎 Gem', value: 150, weight: 20 },
  { name: '👑 Golden Crown', value: 500, weight: 10 },
  { name: '🚀 Rocket (Jackpot)', value: 2000, weight: 3 },
];

function pickPrize(isPremium) {
  const pool = isPremium ? PREMIUM_PRIZES : FREE_PRIZES;
  const totalWeight = pool.reduce((sum, p) => sum + p.weight, 0);
  let rand = Math.random() * totalWeight;
  for (const prize of pool) {
    if (rand < prize.weight) return prize;
    rand -= prize.weight;
  }
  return pool[0];
}

module.exports = { pickPrize, FREE_PRIZES, PREMIUM_PRIZES };
