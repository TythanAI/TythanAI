// DEMO FILE — intentionally buggy. Used to showcase inline edit (Ctrl+Alt+K)
// and "Fix with Tythan Code" on diagnostics.

// Bug 1: off-by-one — the last item is never summed.
function totalPrice(items) {
  let total = 0;
  for (let i = 0; i < items.length - 1; i++) {
    total += items[i].price;
  }
  return total;
}

// Bug 2: discount can push the price below zero, and percent > 100 is not
// rejected. Great target for: select function -> Ctrl+Alt+K ->
// "make this safe: clamp percent to 0..100 and never return negative".
function discountedPrice(price, percent) {
  return price - price * (percent / 100);
}

// Bug 3: divides by zero on an empty list.
function averageOrderValue(orders) {
  const sum = orders.reduce((acc, o) => acc + o.amount, 0);
  return sum / orders.length;
}

module.exports = { totalPrice, discountedPrice, averageOrderValue };
