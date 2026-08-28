// Har bir sovg'a: name, value (ichki ball/reyting uchun), weight, rarity
const FREE_PRIZES = [
  { name: '🔧 CZ75-Auto',         value: 5,    weight: 40, rarity: 'common'    },
  { name: '🔫 Tec-9 | Titanium',  value: 15,   weight: 25, rarity: 'uncommon'  },
  { name: '💐 P250 | Valence',     value: 25,   weight: 18, rarity: 'uncommon'  },
  { name: '🎁 MP9 | Wild Lily',    value: 50,   weight: 10, rarity: 'rare'      },
  { name: '💎 Glock | Fade',       value: 150,  weight: 5,  rarity: 'epic'      },
  { name: '👑 Desert Eagle | Gold', value: 500, weight: 2,  rarity: 'legendary' },
];

const PREMIUM_PRIZES = [
  { name: '🔫 Tec-9 | Titanium',    value: 15,   weight: 15, rarity: 'uncommon'  },
  { name: '💐 P250 | Valence',       value: 25,   weight: 18, rarity: 'uncommon'  },
  { name: '🎁 MP9 | Wild Lily',      value: 50,   weight: 22, rarity: 'rare'      },
  { name: '💎 Glock | Fade',         value: 150,  weight: 20, rarity: 'epic'      },
  { name: '👑 Desert Eagle | Gold',  value: 500,  weight: 10, rarity: 'legendary' },
  { name: '🚀 AWP | Dragon Lore',    value: 2000, weight: 3,  rarity: 'legendary' },
];

const CASE_PRIZES = {
  budget: [
    { name: '🔧 CZ75-Auto',         value: 5,   weight: 40, rarity: 'common'   },
    { name: '🔫 Tec-9 | Titanium',  value: 15,  weight: 30, rarity: 'uncommon' },
    { name: '💎 MP9 | Wild Lily',    value: 50,  weight: 20, rarity: 'rare'     },
  ],
  eco: [
    { name: '🔫 Glock-18 | Groundwater', value: 10,  weight: 35, rarity: 'common'   },
    { name: '⚡ P250 | Electric Hive',    value: 30,  weight: 30, rarity: 'uncommon' },
    { name: '🔷 Five-SeveN | Fowl Play',  value: 80,  weight: 20, rarity: 'rare'     },
    { name: '💎 Desert Eagle | Kumicho',  value: 300, weight: 10, rarity: 'epic'     },
    { name: '👑 Glock | Fade',            value: 800, weight: 5,  rarity: 'legendary'},
  ],
  sniper: [
    { name: '🎯 SSG 08 | Abyss',      value: 50,   weight: 35, rarity: 'uncommon' },
    { name: '🔭 SCAR-20 | Dusk',      value: 120,  weight: 25, rarity: 'rare'     },
    { name: '⭐ AWP | Hyper Beast',    value: 400,  weight: 15, rarity: 'epic'     },
    { name: '👑 AWP | Dragon Lore',    value: 2000, weight: 3,  rarity: 'legendary'},
  ],
  free: FREE_PRIZES,
};

function pickPrize(isPremium, caseId) {
  let pool;
  if (caseId && CASE_PRIZES[caseId]) {
    pool = CASE_PRIZES[caseId];
  } else {
    pool = isPremium ? PREMIUM_PRIZES : FREE_PRIZES;
  }
  const totalWeight = pool.reduce((sum, p) => sum + p.weight, 0);
  let rand = Math.random() * totalWeight;
  for (const prize of pool) {
    if (rand < prize.weight) return prize;
    rand -= prize.weight;
  }
  return pool[0];
}

module.exports = { pickPrize, FREE_PRIZES, PREMIUM_PRIZES, CASE_PRIZES };
