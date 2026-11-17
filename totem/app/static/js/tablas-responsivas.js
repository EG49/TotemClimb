/* Convierte las tablas largas en tarjetas desplegables en pantallas
   angostas.

   El problema: en un teléfono, una tabla de seis columnas se corta y
   obliga a deslizar de lado para ver el estado o las acciones. Nadie
   desliza: simplemente no ve esas columnas.

   La solución acordada es que cada fila se vea como una tarjeta con
   lo esencial, y que al tocarla se despliegue el resto.

   Por qué en JavaScript y no solo en CSS: para mostrar "Vence:
   12/12/2026" debajo del nombre hace falta el rótulo de la columna,
   que vive en el <thead>. Copiarlo a mano en cada <td> de cada
   plantilla sería nueve archivos que se desincronizan en cuanto
   alguien agrega una columna. Acá se lee de la propia cabecera, así
   que una columna nueva funciona sola.

   La tabla del escritorio no se toca: los atributos que se agregan
   son invisibles mientras la pantalla sea ancha. */

(function () {
  'use strict';

  var ANCHO_ANGOSTO = 760;

  function esAccion(celda) {
    return celda.querySelector('.acciones, button, a.btn-ghost, a.btn-primary') !== null;
  }

  /* Una celda cuyo contenido es solo una pastilla de estado. Si
     además trae texto propio, es una celda de datos corriente y se
     trata como tal. */
  function esInsignia(celda) {
    var pastilla = celda.querySelector('.pill');
    if (!pastilla) return false;
    var resto = celda.textContent.replace(pastilla.textContent, '').trim();
    return resto === '';
  }

  function preparar(tabla) {
    if (tabla.dataset.responsivaLista === '1') return;

    var encabezados = tabla.querySelectorAll('thead th');
    if (!encabezados.length) return;

    var rotulos = Array.prototype.map.call(encabezados, function (th) {
      return th.textContent.trim();
    });

    var filas = tabla.querySelectorAll('tbody tr');
    Array.prototype.forEach.call(filas, function (fila) {
      var celdas = fila.children;

      // Una fila de "no hay nada" ocupa todo el ancho: no es una
      // tarjeta, es un mensaje. Se deja como está.
      if (celdas.length === 1 && celdas[0].hasAttribute('colspan')) {
        fila.classList.add('fila-mensaje');
        return;
      }

      var tieneOculto = false;
      Array.prototype.forEach.call(celdas, function (celda, i) {
        var rotulo = rotulos[i] || '';
        if (rotulo) celda.setAttribute('data-rotulo', rotulo);

        // La primera celda es el resumen: siempre visible. Las que
        // llevan acciones también, porque esconder un botón detrás
        // de un despliegue es peor que mostrarlo.
        if (i === 0) {
          celda.classList.add('celda-resumen');
        } else if (esAccion(celda)) {
          celda.classList.add('celda-acciones');
        } else if (esInsignia(celda)) {
          // El estado es lo primero que se mira en una lista: si una
          // membresía está vigente o vencida, si una factura está por
          // cobrar. Esconderlo detrás de un toque sería el error que
          // esta pantalla viene a corregir.
          celda.classList.add('celda-insignia');
        } else {
          celda.classList.add('celda-detalle');
          // Una celda vacía no merece ocupar espacio ni contar para
          // decidir si la fila se puede desplegar.
          if (celda.textContent.trim() === '' && !celda.children.length) {
            celda.classList.add('celda-vacia');
          } else {
            tieneOculto = true;
          }
        }
      });

      if (!tieneOculto) return;

      fila.classList.add('fila-desplegable');
      fila.setAttribute('tabindex', '0');
      fila.setAttribute('role', 'button');
      fila.setAttribute('aria-expanded', 'false');

      var flecha = document.createElement('span');
      flecha.className = 'flecha-fila';
      flecha.setAttribute('aria-hidden', 'true');
      celdas[0].appendChild(flecha);
    });

    tabla.dataset.responsivaLista = '1';
  }

  function alternar(fila) {
    var abierta = fila.classList.toggle('abierta');
    fila.setAttribute('aria-expanded', abierta ? 'true' : 'false');
  }

  function manejar(evento) {
    if (window.innerWidth > ANCHO_ANGOSTO) return;

    var fila = evento.target.closest('tr.fila-desplegable');
    if (!fila) return;

    // Un clic en un enlace, un botón o un campo tiene que hacer lo
    // suyo, no desplegar la fila.
    if (evento.target.closest('a, button, input, select, label, textarea')) return;

    alternar(fila);
  }

  function porTeclado(evento) {
    if (evento.key !== 'Enter' && evento.key !== ' ') return;
    if (window.innerWidth > ANCHO_ANGOSTO) return;
    var fila = evento.target.closest('tr.fila-desplegable');
    if (!fila || fila !== evento.target) return;
    evento.preventDefault();
    alternar(fila);
  }

  function iniciar() {
    var tablas = document.querySelectorAll('.card.tabla table');
    Array.prototype.forEach.call(tablas, preparar);
    document.addEventListener('click', manejar);
    document.addEventListener('keydown', porTeclado);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }

  // Las listas que se recargan por JavaScript (el panel) vuelven a
  // pedir la preparación.
  window.prepararTablasResponsivas = iniciar;
})();
