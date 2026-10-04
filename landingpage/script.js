'use strict';

const areas = {
  rohbau: {
    kicker: '01 / ROHBAU',
    title: 'Der Anfang der Prozesskette.',
    description: 'Stationen führen die deklarierten Operationen aus. Benötigte Maschinen und Mitarbeitende können die verfügbare Kapazität begrenzen.',
    factors: ['Bearbeitungsdauer der Operationen', 'Maschinenkapazität und Verfügbarkeit', 'Qualifikationen und Schichten']
  },
  lack: {
    kicker: '02 / LACKIEREREI',
    title: 'Prozesse wirken über Stationen hinaus.',
    description: 'Prozesszustände aus früheren Operationen können spätere Verarbeitung und Qualität beeinflussen. Prüfungen liefern beobachtbare Befunde, die vom tatsächlichen Qualitätszustand getrennt bleiben.',
    factors: ['Prozessdauer und Ressourcenbedarf', 'Maschinenzustände und Prozesswirkungen', 'Prüfsensitivität und Nacharbeit']
  },
  puffer: {
    kicker: '03 / PUFFER',
    title: 'Begrenzter Raum zwischen den Prozessen.',
    description: 'Puffer halten Produktionseinheiten zwischen Operationen und Transporten. Ihre Kapazität und die Reihenfolge der Einheiten beeinflussen den weiteren Materialfluss.',
    factors: ['Pufferkapazität', 'Reihenfolge und Priorisierung', 'Transportrouten und Transportressourcen']
  },
  montage: {
    kicker: '04 / ENDMONTAGE',
    title: 'Alle Voraussetzungen müssen zusammenpassen.',
    description: 'Prozesspläne legen fest, welche Anforderungen eine Produktvariante durchläuft. Kompatible Stationen, verfügbare Ressourcen und Qualitätsprüfungen bestimmen die konfigurierten Abläufe.',
    factors: ['Prozessanforderungen je Produktvariante', 'Operationen und benötigte Ressourcen', 'Qualitätsprüfung, Nacharbeit und Ausschuss']
  }
};

const buttons = document.querySelectorAll('[data-area]');
buttons.forEach(button => {
  button.addEventListener('click', () => {
    const area = areas[button.dataset.area];
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    document.getElementById('area-kicker').textContent = area.kicker;
    document.getElementById('area-title').textContent = area.title;
    document.getElementById('area-description').textContent = area.description;
    document.getElementById('area-factors').replaceChildren(...area.factors.map(factor => {
      const item = document.createElement('li');
      item.textContent = factor;
      return item;
    }));
  });
});
