/**
 * 2024-12-31 Se crea nuevamente archivo ya que ahora se conecta a una api desarrollada en django en server 110
 *            ej: http://10.107.194.110:8010/get_tires/?dia=2024-12-31&turno=manana
 * 2024-01-08 Se agrega funcionalidad de popover a las celdas de Irregular en tabla principal
 * 2025-05-13 Error en la suma de cojin y sol, se intercambian, ademas se modifica el backend para incluir el inneliner (cojin)
 * 2025-07-08 Se actualiza api para utilizar proxy inverso con /hora/get_tires/ en vez de :8010/get_tires/
 *            Debido a problemas con una tv que no se puede cambiar la hora, se actualiza la pagina para que tome la fech desde el server, se coloca como atributo en el input, 
 *            para luego ser leido por el js
 * 2025-01-16 Se Agrega el acumulado del dia a HVA el no stock y el irregular.
 */

// Busca el periodo de tiempo del turno anterior, formatea fechas 
function shift() {
  // Formateando fecha
  const fecha = new Date();
  const formato = 'yyyy-mm-dd';
  const map = {
    dd: fecha.getDate(),
    mm: fecha.getMonth() + 1,
    yyyy: fecha.getFullYear()
  };
  const hrs = {
    hh: fecha.getHours(),
    mn: fecha.getMinutes(),
    ss: fecha.getSeconds()
  };
  const hora = hrs.hh + ':' + hrs.mn + ':' + hrs.ss;
  var now = formato.replace(/dd|mm|yyyy/gi, matched => (map[matched] < 10 ? '0' : '') + map[matched]);

  var tAnterior = '';
  var diaAnterior = now;
  switch (true) {
    case hrs.hh >= 7 && hrs.hh < 15:
      tAnterior = 'manana';
      break;

    case hrs.hh >= 15 && hrs.hh < 23:
      tAnterior = 'tarde';
      break;

    case hrs.hh >= 23:
      tAnterior = 'noche';
      break;

    case hrs.hh < 7:
      tAnterior = 'noche';
      const diaTmp = new Date(fecha.getTime() - (1000 * 60 * 60 * 24));
      const mapTmp = {
        dd: diaTmp.getDate(),
        mm: diaTmp.getMonth() + 1,
        yyyy: diaTmp.getFullYear()
      };
      diaAnterior = formato.replace(/dd|mm|yyyy/gi, matched => (mapTmp[matched] < 10 ? '0' : '') + mapTmp[matched]);
      break;

    default:
      break;
  }

  var retTmp = {
    turno: tAnterior,
    horario: diaAnterior
  };
  return retTmp;
}

// Trae los datos de target de las areas
async function getTargets() {
  const url = 'assets/php/get_target.php';
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Network or API error:", error.message);
  }
}

// Trae los datos desde la API
function get_data(periodoArray) {
  const url = `http://10.107.194.110/hora/get_tires/`;
  // const url = `http://10.107.194.110:8010/get_tires/`;
  const urlWithParams = `${url}?dia=${periodoArray.horario}&turno=${periodoArray.turno}`;

  fetch(urlWithParams)
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      if (data.status === "success") {
        // console.log(data);
        showTables(data);
      } else {
        console.error(`API Error: ${data.message}`);
      }
    })
}

// Crea la celdad de la tabla
function createCell(val, target, i, side, title, classId, pop) {
  // Crea las celdas segun los datos entregados, cambia de color segun corresponda
  // 2024.01.05 si se agrega un val en blanco se crea una celda en blanco
  // 2024.01.19 se modifica lo anterior, agrega el color blanco a la celda para que no sea tipo bold la letra
  val = parseFloat(val) == 0 ? 0 : val
  var htmlCell = ''
  var clase = 'text-center table-success', border = '', style = ''
  var classRow = (classId != '' && classId != undefined) ? ' ' + classId : ''
  switch (side) {
    case 'L':
      border = ' border-start'
      style = 'border-left-color: #826e6e !important'
      break;
    default:
      break;
  }
  // cuando exite un popover...
  if (pop === 'pop') {
    var clasePop = ''
    var checkPop = '<span class="mdi mdi-check-bold"></span>'
    // Verifica si es mayor o menor
    if (val != undefined && (parseFloat(val) * i < parseFloat(target) * i)) {
      clase = 'text-center table-danger'
      checkPop = '<span class="mdi mdi-exclamation-thick" style="color:red"></span>'
    }

    // construccion de la clase
    if (target === '') {
      clasePop = `text-center${border}`
    } else {
      clasePop = clase + border
    }

    // Construccion del html y popover -> el popover tiene contenido html 
    var htmlPop = `<td class="${clasePop}" style="${style}">
    <span 
    class="${classRow}" 
    tabindex="0" 
    data-bs-toggle="popover" 
    data-bs-trigger="manual" 
    data-bs-html="true" 
    data-bs-content="<i class='fa-duotone fa-spinner fa-spin-pulse' style='--fa-primary-color: #186d41; --fa-secondary-color: #000000;'></i> Buscando..."
    >${checkPop} ${val} 
    </span>
    </td>`
    // data-bs-content="<i class='fa-duotone fa-spinner fa-spin-pulse' style='--fa-primary-color: #186d41; --fa-secondary-color: #000000;'></i> Buscando..."
    // data-bs-content="<table><th>Hola</th></table>" 
    // data-bs-trigger="focus" 

    return htmlPop
  }
  if (val === '') { return `<td class="${border}" style="${style}"></td>` }
  if (target === '') { return `<td class="text-center${border}" style="${style}">${val}</td>` }
  // if (title === 'T') { return `<td class="text-center${border}" style="${style}"><b>${val}</b></td>` }
  var check = '<span class="mdi mdi-check-bold"></span>'
  if (val != undefined && (parseFloat(val) * i > parseFloat(target) * i)) {
    htmlCell += `<td class="${clase + border + classRow}" style="${style}">${check} ${val}</td>`
  } else {
    clase = 'text-center table-danger'
    check = '<span class="mdi mdi-exclamation-thick" style="color:red"></span>'
    htmlCell += `<td class="${clase + border + classRow}" style="${style}">${check} ${val == undefined ? 0 : val}</td>`
  }
  return htmlCell
}

// Crea la tabla principal de hora a hora, la primeda con la informacion global
function createTablePrincipal(targets, jsonData) {
  // Elimina los relojes dando vueltas y muestra la tabla
  var spinElement = document.getElementById("spin");
  var tblDataElement = document.getElementById("tbl-data");
  spinElement.style.display = "none";
  spinElement.classList.remove('d-flex')
  tblDataElement.classList.remove("d-none");
  tblDataElement.classList.add("fade-in", "active");
  document.getElementById('refresh-icon').classList.remove('mdi-spin')

  // Procesamiento de los targets
  var target = JSON.parse(targets.targets_values)

  // Datos target segun base de datos ya datos dados por el usuario
  var prodHVA = target['target_building_tires']
  var prodCura = target['target_curing_tires']
  var prodAcre = target['target_stocked_tires']
  var scrapGTarget = target['green_scrap']
  var scrapCTarget = target['curing_scrap']
  var curaNotireTarget = 1.5
  var curaCodigoTarget = 0.8
  var irregularTotal = target.irregular_apex + target.irregular_gum + target.irregular_lat + target.irregular_ovrl + target.irregular_ply + target.irregular_steel + target.irregular_tread
  // Target de mixer segun el turno
  switch (document.querySelector('input[name="inlineRadioOptions"]:checked').value) {
    case 'manana':
      var prodMixer = target['target_mix_1_1'] + target['target_mix_2_1'] + target['target_mix_3_1'] + target['target_mix_3_1'] + target['target_mix_3_1']
      break;
    case 'tarde':
      var prodMixer = target['target_mix_1_2'] + target['target_mix_2_2'] + target['target_mix_3_2'] + target['target_mix_3_2'] + target['target_mix_3_2']
      break;
    case 'noche':
      var prodMixer = target['target_mix_1_3'] + target['target_mix_2_3'] + target['target_mix_3_3'] + target['target_mix_3_3'] + target['target_mix_3_3']
      break;
    default:
      break;
  }

  // Construccion del cuerpo de la tabla principal de hora a hora
  let html = "";
  Object.keys(jsonData.data).forEach((date) => {
    if (date === "total" || date === "dia") return; // Omitir las claves "total" y "dia"
    html += `<tr>
        <td>${date}</td>
        ${createCell(jsonData.data[date].mixer.batch, prodMixer / 8, 1)}
        ${createCell(jsonData.data[date].hva.prod, prodHVA / 3 / 8, 1, 'L')}
        ${createCell(jsonData.data[date].hva.scrap, scrapGTarget / 3 / 8, -1)}
        ${createCell(jsonData.data[date].hva.break, target['breakdown_building'], -1, '', '', 'breakHVA', 'pop')}
        ${createCell(jsonData.data[date].hva.noStock.total, 13, -1, '', '', '')}
        ${createCell(jsonData.data[date].hva.cambio_codigo, 3.3, -1, '', '', 'CC_hva', 'pop')}
        ${createCell(jsonData.data[date].hva.irregular.total, irregularTotal / 3 / 8, -1, '', '', 'irregularHVA', 'pop')}
        ${createCell(jsonData.data[date].cura.prod, prodCura / 3 / 8, 1, 'L')}
        ${createCell(jsonData.data[date].cura.scrap, scrapCTarget / 3 / 8, -1)}
        ${createCell(jsonData.data[date].cura.break, target['breakdown_curing'], -1)}
        ${createCell(jsonData.data[date].cura.noTire, curaNotireTarget, -1)}
        ${createCell(jsonData.data[date].cura.cambio_codigo, curaCodigoTarget, -1)}
        ${createCell(jsonData.data[date].acreditado.acreditado, prodAcre / 3 / 8, 1, 'L')}
        </tr>`
  })

  // Creacion celdas Total Turno y Total dia tabla principal hora a hora
  html += `<tr class="table-group-divider"style="border-top-color: #826e6e;">
        <th>Total Turno</th>
        ${createCell(jsonData.data.total.mixer.batch, prodMixer, 1, '', 'T')}
        ${createCell(jsonData.data.total.hva.prod, prodHVA / 3, 1, 'L', 'T')}
        ${createCell(jsonData.data.total.hva.scrap, scrapGTarget / 3, -1, '', 'T')}
        ${createCell(jsonData.data.total.hva.break, target['breakdown_building'], -1, '', 'T')}
        ${createCell(jsonData.data.total.hva.noStock, 13 * 8, -1, '', 'T')}
        ${createCell(jsonData.data.total.hva.cambio_codigo, 3.3, -1, '', 'T')}
        ${createCell(jsonData.data.total.hva.irregular, irregularTotal / 3, -1)}
        ${createCell(jsonData.data.total.cura.prod, prodCura / 3, 1, 'L', 'T')}
        ${createCell(jsonData.data.total.cura.scrap, scrapCTarget / 3, -1, '', 'T')}
        ${createCell(jsonData.data.total.cura.break, target['breakdown_curing'], -1, '', 'T')}
        ${createCell(jsonData.data.total.cura.noTire, curaNotireTarget, -1, '', 'T')}
        ${createCell(jsonData.data.total.cura.cambio_codigo, curaCodigoTarget, -1, '', 'T')}
        ${createCell(jsonData.data.total.acreditado.acreditado, prodAcre / 3, 1, 'L', 'T')}
        </tr>
        <tr class="table-group-divider"style="border-top-color: #826e6e;">
        <th>Total Día</th>
        ${createCell(jsonData.data.dia.mixer.batch, '', 1)}
        ${createCell(jsonData.data.dia.hva.prod, '', 1, 'L')}
        ${createCell(jsonData.data.dia.hva.scrap, '', 1)}
        ${createCell('', '', 1)}
        ${createCell(jsonData.data.dia.hva.noStock, '', 1)}
        ${createCell('', '', 1)}
        ${createCell(jsonData.data.dia.hva.irregular, '', 1)}
        ${createCell(jsonData.data.dia.cura.prod, '', 1, 'L')}
        ${createCell(jsonData.data.dia.cura.scrap, '', 1)}
        ${createCell('', '', 1)}
        ${createCell('', '', 1)}
        ${createCell('', '', 1)}
        ${createCell(jsonData.data.dia.acreditado.acreditado, '', 1, 'L')}
        </tr>
      `
  document.getElementById("datas").innerHTML = html
}

// Creacion de tabla de Irregular de APS
function createTableIrregular(targets, jsonData) {
  // Efecto fade in/out de la tabla
  var tblDataElementIrr = document.getElementById("tbl-irregular");
  tblDataElementIrr.classList.remove("d-none");
  tblDataElementIrr.classList.add("fade-in", "active");

  // Targets
  var target = JSON.parse(targets.targets_values)
  var irregularTotal = target.irregular_apex + target.irregular_gum + target.irregular_lat + target.irregular_ovrl + target.irregular_ply + target.irregular_steel + target.irregular_tread

  // Creacion de variable de totales
  var beadTotal = 0, brkTotal = 0, linnerTotal = 0, plyTotal = 0, solTotal = 0, treadTotal = 0, swTotal = 0, totalTotal = 0
  var beadTotalNS = 0, brkTotalNS = 0, linnerTotalNS = 0, plyTotalNS = 0, solTotalNS = 0, treadTotalNS = 0, swTotalNS = 0, totalTotalNS = 0


  // Construccion del cuerpo de la tabla principal de hora a hora
  let html = "";
  Object.keys(jsonData.data).forEach((date) => {
    if (date === "total" || date === "dia") return; // Omitir las claves "total" y "dia"

    html += `
        <tr>
          <td>${date}</td>
          ${createCell(jsonData.data[date].hva.irregular.Bead, target.irregular_apex / 3 / 8, -1, '', '', 'beadHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Breaker, target.irregular_steel / 3 / 8, -1, '', '', 'breakerHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Cojin, target.irregular_gum / 3 / 8, -1, '', '', 'linnerHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Ply, target.irregular_ply / 3 / 8, -1, '', '', 'plyHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Overlay, target.irregular_ovrl / 3 / 8, -1, '', '', 'solHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Tread, target.irregular_tread / 3 / 8, -1, '', '', 'treadHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.Sidewall, target.irregular_lat / 3 / 8, -1, '', '', 'sidewallHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.irregular.total, irregularTotal / 3 / 8, -1)}
        </tr>`

    // Suma de totales
    beadTotal += jsonData.data[date].hva.irregular.Bead == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Bead)
    brkTotal += jsonData.data[date].hva.irregular.Breaker == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Breaker)
    linnerTotal += jsonData.data[date].hva.irregular.Overlay == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Overlay)
    plyTotal += jsonData.data[date].hva.irregular.Ply == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Ply)
    solTotal += jsonData.data[date].hva.irregular.Cojin == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Cojin)
    treadTotal += jsonData.data[date].hva.irregular.Tread == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Tread)
    swTotal += jsonData.data[date].hva.irregular.Sidewall == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.Sidewall)
    totalTotal += jsonData.data[date].hva.irregular.total == undefined ? 0 : parseFloat(jsonData.data[date].hva.irregular.total)

  })

  // Creacion celdas Total Turno
  html += `
      <tr class="table-group-divider"style="border-top-color: #826e6e;">
        <th>Total Turno</th>
        ${createCell(beadTotal.toFixed(2), target.irregular_apex / 3, -1)}
        ${createCell(brkTotal.toFixed(2), target.irregular_steel / 3, -1)}
        ${createCell(solTotal.toFixed(2), target.irregular_gum / 3, -1)}
        ${createCell(plyTotal.toFixed(2), target.irregular_ply / 3, -1)}
        ${createCell(linnerTotal.toFixed(2), target.irregular_ovrl / 3, -1)}
        ${createCell(treadTotal.toFixed(2), target.irregular_tread / 3, -1)}
        ${createCell(swTotal.toFixed(2), target.irregular_lat / 3, -1)}
        ${createCell(totalTotal.toFixed(2), irregularTotal / 3, -1)}
      </tr>`
  document.getElementById('datasIrr').innerHTML = html
}

// Creacion de tabla de No Stock de APS
function createTableNoStock(targets, jsonData) {
  // Efecto fade in/out de la tabla
  var tblDataElementIrr = document.getElementById("tbl-noStock");
  tblDataElementIrr.classList.remove("d-none");
  tblDataElementIrr.classList.add("fade-in", "active");

  // Targets
  var target = JSON.parse(targets.targets_values)
  var irregularTotal = target.irregular_apex + target.irregular_gum + target.irregular_lat + target.irregular_ovrl + target.irregular_ply + target.irregular_steel + target.irregular_tread

  // Creacion de variable de totales
  var beadTotal = 0, brkTotal = 0, linnerTotal = 0, plyTotal = 0, solTotal = 0, treadTotal = 0, swTotal = 0, totalTotal = 0
  var beadTotalNS = 0, brkTotalNS = 0, linnerTotalNS = 0, plyTotalNS = 0, solTotalNS = 0, treadTotalNS = 0, swTotalNS = 0, totalTotalNS = 0


  // Construccion del cuerpo de la tabla principal de hora a hora
  let html = "";
  Object.keys(jsonData.data).forEach((date) => {
    if (date === "total" || date === "dia") return; // Omitir las claves "total" y "dia"

    html += `
        <tr>
          <td>${date}</td>
          ${createCell(jsonData.data[date].hva.noStock.Bead, target.irregular_apex / 3 / 8, -1, '', '', 'beadHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Breaker, target.irregular_steel / 3 / 8, -1, '', '', 'breakerHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Cojin, target.irregular_gum / 3 / 8, -1, '', '', 'linnerHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Ply, target.irregular_ply / 3 / 8, -1, '', '', 'plyHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Overlay, target.irregular_ovrl / 3 / 8, -1, '', '', 'solHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Tread, target.irregular_tread / 3 / 8, -1, '', '', 'treadHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.Sidewall, target.irregular_lat / 3 / 8, -1, '', '', 'sidewallHVA', 'pop')}
          ${createCell(jsonData.data[date].hva.noStock.total, irregularTotal / 3 / 8, -1)}
        </tr>`

    // Suma de totales
    beadTotal += jsonData.data[date].hva.noStock.Bead == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Bead)
    brkTotal += jsonData.data[date].hva.noStock.Breaker == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Breaker)
    linnerTotal += jsonData.data[date].hva.noStock.Overlay == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Cojin)
    plyTotal += jsonData.data[date].hva.noStock.Ply == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Ply)
    solTotal += jsonData.data[date].hva.noStock.Cojin == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Overlay)
    treadTotal += jsonData.data[date].hva.noStock.Tread == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Tread)
    swTotal += jsonData.data[date].hva.noStock.Sidewall == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.Sidewall)
    totalTotal += jsonData.data[date].hva.noStock.total == undefined ? 0 : parseFloat(jsonData.data[date].hva.noStock.total)

  })

  // Creacion celdas Total Turno
  html += `
      <tr class="table-group-divider"style="border-top-color: #826e6e;">
        <th>Total Turno</th>
        ${createCell(beadTotal.toFixed(2), target.irregular_apex / 3, -1)}
        ${createCell(brkTotal.toFixed(2), target.irregular_steel / 3, -1)}
        ${createCell(linnerTotal.toFixed(2), target.irregular_gum / 3, -1)}
        ${createCell(plyTotal.toFixed(2), target.irregular_ply / 3, -1)}
        ${createCell(solTotal.toFixed(2), target.irregular_ovrl / 3, -1)}
        ${createCell(treadTotal.toFixed(2), target.irregular_tread / 3, -1)}
        ${createCell(swTotal.toFixed(2), target.irregular_lat / 3, -1)}
        ${createCell(totalTotal.toFixed(2), irregularTotal / 3, -1)}
      </tr>`
  document.getElementById('datasNoStock').innerHTML = html
}

/**
 * Muestra las tablas basadas en los datos JSON proporcionados.
 *
 * @param {Object} jsonData - Los datos JSON que contienen la información para las tablas.
 * 
 * @returns {void}
 * 
 * @description Esta función obtiene los objetivos de las áreas y, si se obtienen correctamente,
 *              crea varias tablas: la tabla principal de hora a hora, la tabla de Irregular de APS,
 *              y la tabla de No Stock de APS. En caso de error al obtener los objetivos, se registra
 *              un mensaje de error en la consola.
 */
function showTables(jsonData) {
  // llama los targets de las areas
  getTargets().then(targets => {
    if (targets) {
      createTablePrincipal(targets, jsonData) // Crea la tabla principal de hora a hora, la primeda con la informacion global
      createTableIrregular(targets, jsonData) // Crea la tabla de Irregular de APS
      createTableNoStock(targets, jsonData) // Crea la tabla de No Stock de APS
    }
  }).catch(error => {
    console.error("Error fetching targets:", error.message);
  });
}

// Construye la tabla de los datos de maquinas criticas Breakdown
function generateTableContent(maq) {
  var tableHtml = ``
  if (maq == undefined) {
    tableHtml = `<div class="text-center mt-3" style="font-size:.685rem">No hay registros</div>`
  } else {
    tableHtml += `
      <table class="table table-sm table-borderless" style="font-size:.685rem; margin-bottom:0;">
        <thead>
          <tr>
              <th scope="col">Máquina</th>
              <th scope="col">Razón</th>
              <th scope="col">Descripción</th>
              <th scope="col">Minutos</th>
          </tr>
        </thead>
        <tbody>
      `

    for (let i = 0; i < maq.length; i++) {
      tableHtml += `
        <tr>
          <td scope="row">${maq[i].maquina}</td>
          <td>${maq[i].downReason}</td>
          <td>${maq[i].downDescription}</td>
          <td>${maq[i].downMinutes}</td>
        </tr>
      `
    }

    tableHtml += `
        </tbody>
      </table>
    `
  }

  return tableHtml;
}

// Construye la tabla de los datos de maquinas criticas C. Change
function generateTableContent(maq) {
  var tableHtml = ``
  if (maq == undefined) {
    tableHtml = `<p class="text-center mt-3">No hay registros</p>`
  } else {
    tableHtml += `
      <table class="table table-sm table-borderless" style="font-size:.685rem; margin-bottom:0;">
        <thead>
          <tr>
              <th scope="col">Máquina</th>
              <th scope="col">Descripción</th>
              <th scope="col">Minutos</th>
          </tr>
        </thead>
        <tbody>
      `

    for (let i = 0; i < maq.length; i++) {
      tableHtml += `
        <tr>
          <td scope="row">${maq[i].maquina}</td>
          <td>${maq[i].downDescription}</td>
          <td>${maq[i].downMinutes}</td>
        </tr>
      `
    }

    tableHtml += `
        </tbody>
      </table>
    `
  }

  return tableHtml;
}

// Trae los datos de las maquinas criticas de construccion Cambio de codigo
function get_machCC(f, popover) {
  var f_start = f + ':00:00'
  var url = 'assets/php/get_hvaInfoCC.php?start=' + f_start
  return fetch(url)
    .then(response => response.json())
    .then((data) => {
      return data
    })
}

// Trae los datos de las maquinas criticas de construccion Irregular
function get_machIrr(f, mat) {
  var f_start = f + ':00:00'
  var url = 'assets/php/get_IrrInfo.php?start=' + f_start + '&mat=' + mat
  return fetch(url)
    .then(response => response.json())
    .then((data) => {
      return data
    })
}

// Trae los datos de las maquinas criticas de construccion Breakdown
function get_machBrk(f, popover) {
  var f_start = f + ':00:00'
  var url = 'assets/php/get_hvaInfo.php?start=' + f_start
  return fetch(url)
    .then(response => response.json())
    .then((data) => {
      return data
    })
}

// Trae desde PHP los datos del turno y horario actual
async function get_current_shift() {
  try {
    const response = await fetch('./assets/php/get_time_shift.php');
    if (!response.ok) {
      throw new Error('Error en la solicitud');
    }

    const data = await response.json();

    // Retornar los datos para usarlos fuera
    return {
      turno: data.turno,
      fecha: data.fecha
    };

  } catch (error) {
    console.error('Hubo un error al obtener los datos:', error);
    return null;  // O puedes lanzar el error si quieres que falle externamente
  }
}


// Time Picker
const period = shift()
document.getElementById(period['turno']).checked = true
$(function () {
  $('input[name="time"]').daterangepicker({
    singleDatePicker: true,
    showDropdowns: true,
    minDate: '2023-10-24',
    maxDate: period['horario'],
    locale: { format: 'YYYY-MM-DD', },
  })
  range = $("#dash-daterange").data('daterangepicker')
  fechaSearch = range.startDate.format('YYYY-MM-DD')

  // Obtiene desde el php de inicio horahora.php la fecha escrita en el atributo de input
  let campoFecha = document.getElementById('dash-daterange');
  let hoy = campoFecha.getAttribute('fecha');

  // Obtiene desde Front el turno en que se encuentra
  let turno = document.getElementById('turnos').getAttribute('turno');

  // carga la fecha y el turno actual en el input
  campoFecha.value = hoy;
  document.getElementById(turno).checked = true;

  var periodSearch = {
    turno: turno,
    horario: hoy,
  }

  get_data(periodSearch)


  // Ejecuta get_data cada 5 minutos (300000 milisegundos)
  setInterval(async function () {
    const current_shift = await get_current_shift();

    if (!current_shift) return;  // Evita errores si hubo un problema

    const periodSearchUpdated = {
      turno: current_shift.turno,
      horario: current_shift.fecha,
    };

    document.getElementById(periodSearchUpdated.turno).checked = true;
    document.getElementById('dash-daterange').value = periodSearchUpdated.horario;

    console.log('done');
    get_data(periodSearchUpdated);
  }, 300000); // 5 minutos
})


// ---------------------------- EVENTOS ----------------------------

// Al presionar sobre ACTUALIZAR hace cambios en la pagina
$("#refresh").click(function () {
  // Vuelve a cargar el grafico con los datos ingresados en el input
  fechaSearch = range.startDate.format('YYYY-MM-DD')
  var periodSearch = {
    turno: document.querySelector('input[name="inlineRadioOptions"]:checked').value,
    horario: fechaSearch,
  }
  var fecha = shift()
  document.getElementById('refresh-icon').classList.add('mdi-spin')
  get_data(periodSearch)
})

// Al presionar en APPLY, se hace los cambios en la pagina
$('#dash-daterange').on('apply.daterangepicker', function (ev, picker) {
  fechaSearch = range.startDate.format('YYYY-MM-DD')
  var periodSearch = {
    turno: document.querySelector('input[name="inlineRadioOptions"]:checked').value,
    horario: fechaSearch,
  }

  var fecha = shift()
  get_data(periodSearch)
})

document.addEventListener('DOMContentLoaded', function () {
  // Espera a que el DOM esté completamente cargado

  // --------------------- Presionar sobre celda de Breakdown construccion ---------------------

  // Obtener la tabla
  var tblData = document.getElementById('tbl-data');

  // Agregar un event listener a la tabla para la delegación de eventos
  tblData.addEventListener('click', function (event, d) {
    // Verificar si el clic ocurrió en una fila de "Construcción-Break"
    if (event.target.classList.contains('breakHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.breakHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machBrk(fecha)
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Construcción C.Change"
    if (event.target.classList.contains('CC_hva')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.CC_hva');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machCC(fecha)
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Irregular"
    if (event.target.classList.contains('irregularHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.irregularHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, '')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

  });


  // --------------------- Presionar sobre celda de materiales ---------------------
  // Obtener la tabla
  var tblDataIrregular = document.getElementById('tbl-irregular');
  // Agregar un event listener a la tabla para la delegación de eventos
  tblDataIrregular.addEventListener('click', function (event, d) {

    // Verificar si el clic ocurrió en una fila de "Bead"
    if (event.target.classList.contains('beadHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.beadHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'bead')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Breaker"
    if (event.target.classList.contains('breakerHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.breakerHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'breaker')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Linner"
    if (event.target.classList.contains('linnerHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.linnerHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'linner')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Ply"
    if (event.target.classList.contains('plyHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.plyHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'ply')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "Sol"
    if (event.target.classList.contains('solHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.solHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'sol')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "tread"
    if (event.target.classList.contains('treadHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.treadHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'tread')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }

    // Verificar si el clic ocurrió en una fila de "sw"
    if (event.target.classList.contains('sidewallHVA')) {

      // Obtencion de los datos de las maquinas criticas y apertura popover
      var targetCell = event.target.closest('.sidewallHVA');
      var targetRow = event.target.closest('tr')
      var fecha = tblData.rows[targetRow.rowIndex].cells[0].textContent

      // Promesa de los datos
      get_machIrr(fecha, 'sw')
        .then((res) => {
          var maqCrit = res
          mySpan = event.target.closest('span')
          var popover = new bootstrap.Popover(mySpan, {
            html: true,
            content: function () {
              // Genera el contenido de la tabla
              var tableContent = generateTableContent(maqCrit);

              // Crea un contenedor para la tabla
              var container = document.createElement('div');
              container.innerHTML = tableContent;

              return container;
            },
            trigger: 'focus'
          });
          // Muestra el popover
          popover.show();

          // Despues de abierto el popover este se cierra a los 5seg
          mySpan.addEventListener('shown.bs.popover', function () {
            // Cierra manualmente el popover después de 5 segundos
            setTimeout(function () {
              popover.hide();
            }, 5000);
          });
        })
    }
  });
});