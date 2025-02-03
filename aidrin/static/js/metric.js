/*
* ************************ FUNCTIONS MOVED FROM HTML PAGE ************************
*/
//Unsure if this is still needed: a page reload is no longer needed but further testing is required to ensure
//I don't break anything
$(document).ready(function () {
    $('#file').on('change', function () {
        fetch("{{ url_for('retrieve_uploaded_file') }}")
            .then(response => response.blob())  // Convert  to a Blob
            .then(fileBlob => {
                //append to form
                var formData = new FormData();
                formData.append('file', fileBlob, 'filename'); 

                // Send the FormData via POST request
                fetch(window.location.href, {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => console.log('File uploaded successfully', data))
                .catch(error => console.error('Error:', error));
        })
        .catch(error => console.error('Error fetching file:', error));

        var file = "{{ url_for('retrieve_uploaded_file') }}";
        var fileBlob = new Blob([file], {type: "application/octet-stream"})
        var formData = new FormData();
        formData.append('file', fileBlob);

        $.ajax({
            url: '/feature_set',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function (response) {
                if (response.success) {

                    // Check if either categorical or numerical features exist in the response
                    if ('categorical_features' in response) {
                        createDropdown(response.categorical_features, 'catFeaturesDropdown');
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox1','categorical features for feature relevancy')
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox2','quasi identifiers to measure single attribute risk score')
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox3','quasi identifiers to measure multiple attribute risk score')

                    }

                    if ('numerical_features' in response) {
                        createDropdown(response.numerical_features, 'numFeaturesDropdownFeaRel');
                        createDropdown(response.numerical_features, 'numFeaturesDropdownPriv');
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox1','numerical features for feature relevancy')
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox2',"numerical features to add noise")
                    }

                    if ('all_features' in response){
                        createDropdown(response.all_features,'allFeaturesDropdownRepRate');
                        createDropdown(response.all_features,'allFeaturesDropdownStatRate1');
                        createDropdown(response.all_features,'allFeaturesDropdownStatRate2');
                        createDropdown(response.all_features,'allFeaturesDropdownRealRep');
                        createDropdown(response.all_features,'allFeaturesDropdownFeaRel');
                        createDropdown(response.all_features,'allFeaturesDropdownClIm');
                        createDropdown(response.all_features,'allFeaturesDropdownMMS');
                        createDropdown(response.all_features,'allFeaturesDropdownMMM');
                        createDropdown(response.all_features,'allFeaturesDropdownCondDemoDis1');
                        createDropdown(response.all_features,'allFeaturesDropdownCondDemoDis2');
                    }

                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
            }
        });
    });

    function createDropdown(features, dropdownId) {
        var dropdown = $('#' + dropdownId);
        dropdown.empty(); // Clear previous options

        // Add default options
        dropdown.append($('<option value="" disabled>Select a feature</option>'));

        // Populate the dropdown with options from the response
        for (var i = 0; i < features.length; i++) {
            dropdown.append($('<option>').text(features[i]));
        }
    }
    function createCheckboxContainer(features, tableId, nameTag) {
       
        var table = $('#' + tableId);
        table.empty(); // Clear previous content

        var columns = 4; // Maximum number of columns

        for (var i = 0; i < features.length; i++) {
            if (i % columns === 0) {
                var row = $('<tr>');
                table.append(row);
            }

            var checkbox = $('<input>').attr({
                type: 'checkbox',
                class: 'material-checkbox',
                id: tableId+'checkbox_' + i, // Generate unique ids so all buttons work
                name: nameTag, // Set the name attribute
                value: features[i]
            });

            var span = $('<span>').addClass('checkmark');

            var label = $('<label>')
                .attr('class','material-checkbox')
                .attr('for', tableId+'checkbox_' + i)
                .attr('id', tableId+'checkbox_' + i);

            label.append(checkbox).append(span).append(features[i]);
            var cell = $('<td>').append(label);

            row.append(cell);
        }
    }
});


//generate summary statistics
$(document).ready(function () {
    document.getElementById('uploadForm').addEventListener('submit', function(event) {
        event.preventDefault(); // In order to prevent autoreload on sumbit, so that visualization data can be added.
    });

        var formData = new FormData();
        var file = "{{ url_for('retrieve_uploaded_file') }}";
        formData.append('file', file);
       
        $.ajax({
            url: '/summary_statistics',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function (response) {
                if (response.success) {
                    
                    $('#recordsCount').text(response.records_count);
                    $('#catFeatures').text(response.categorical_features);
                    $('#numFeatures').text(response.numerical_features);
                   

                    // Display additional summary statistics
                    
                    var statisticsHTML = '<h2 style="text-align:center">Summary Statistics Table</h2><table>';
                    statisticsHTML += '<tr><th>Statistic</th>'; // Bold header for the "Statistic" column

                    // Iterate over the keys to create columns (excluding the first key)
                    for (var key in response.summary_statistics) {
                        statisticsHTML += '<th>' + key + '</th>';
                    }
                    statisticsHTML += '</tr>'; // End of the header row

                    // Iterate over the statistics for each key
                    for (var statKey in response.summary_statistics[key]) {
                        statisticsHTML += '<tr><td><strong>' + statKey + '</strong></td>'; // Bold row for the "Feature" column

                        // Iterate over the keys to get values for each column
                        for (var key in response.summary_statistics) {
                            var statValue = response.summary_statistics[key][statKey];

                            statisticsHTML += '<td>' + statValue + '</td>';
                        }
                        statisticsHTML += '</tr>'; // End of the row
                    }

                    statisticsHTML += '</table>';
                    
                    statisticsHTML += '<br><p id="Statresult" ><strong>Number of Features:</strong> <span id="featuresCount">' + response.features_count + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Number of Data Points:</strong> <span id="recordsCount">' + response.records_count + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Categorical Features:</strong> <span id="catFeatures">' + response.categorical_features + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Numerical Features:</strong> <span id="numFeatures">' + response.numerical_features + '</span></p><br>';
                   
                    $('#summaryStatistics').html(statisticsHTML);
                    // Display histograms
                    var histogramsContainer = $('#histogramsContainer');
                    histogramsContainer.empty();
                    histogramsContainer.append('<br><h2 style="margin-top:0px;">Summary Statistic Plots</h2>'); // Add heading for histograms
                    histogramsContainer.append('<div class="slideshow-container">'); // Add container for the slideshow
                    var i = 1;
                    for (var feature in response.histograms) {
                        var base64Image = response.histograms[feature];
                        var img = document.createElement('img');
                        img.src = 'data:image/png;base64,' + base64Image;
                        img.alt = feature + ' Histogram';
                        /* Image carousel wrapper*/
                        let slideDiv = $('<div class="mySlides fade"></div>');
                        //show the first plot by default
                        if(i==1){
                            slideDiv.css('display','block');
                        }
                        i++;
                        slideDiv.append(img);
                        histogramsContainer.append(slideDiv);

                    }
                    /* dot switcher */

                    histogramsContainer.append('<div style="text-align:center">');
                    for(var j=1; j<i; j++){
                        histogramsContainer.append('<span class="dot" onclick="currentSlide('+j+')"></span>');
                        //darken the first by default
                       if(j==1){
                            $('.dot').addClass('activeDot');
                        }
                    }
                    histogramsContainer.append('</div></div>');
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
            }
        });
    });
    // Slideshow control for the histograms
    // Thumbnail image controls
    function currentSlide(n) {
      showSlides(slideIndex = n);
    }
    function showSlides(n) {
      let i;
      let slides = document.getElementsByClassName("mySlides");
      let dots = document.getElementsByClassName("dot");
      if (n > slides.length) {slideIndex = 1}
      if (n < 1) {slideIndex = slides.length}
      for (i = 0; i < slides.length; i++) {
        slides[i].style.display = "none";
      }
      for (i = 0; i < dots.length; i++) {
        dots[i].className = dots[i].className.replace(" activeDot", "");
      }
      slides[slideIndex-1].style.display = "block";
      dots[slideIndex-1].className += " activeDot";
    }


//generate dropdown when features of the dataset are required to select
$(document).ready(function() {
        //for some reason the jinja path will only work if I add the file to a form?
        //if this is where the dropdowns are added I think this is the problem
        var formData = new FormData();
        var file = "{{ url_for('retrieve_uploaded_file') }}";
        formData.append('file', file);
        var file = new Blob([formData.get('file')], { type: file.type });
        console.log(file);
        if (file) {
            var reader = new FileReader();
            reader.onload = function(e) {
                var content = e.target.result;
                var lines = content.split('\n');
                if (lines.length > 0) {
                    var columns = lines[0].split(',');
                    displayColumns(columns);
                }
            };
            reader.readAsText(file);
        }
    

    var checkboxesLoaded = false;

    function displayColumns(columns) {

        // Checkboxes
        if (!checkboxesLoaded) {
            var checkboxContainer = $('#correlationCheckboxContainer');
            var table = $('<table>').appendTo(checkboxContainer);
            var row, cell;

            for (var i = 0; i < columns.length; i++) {
                if (i % 4 === 0) {
                    // Start a new row for every 4 columns
                    row = $('<tr>').appendTo(table);
                }

                cell = $('<td>').appendTo(row);

                var checkbox = $('<input type="checkbox" class="material-checkbox">')
                    .attr('id', 'checkbox_' + columns[i])
                    .attr('value', columns[i])
                    .attr('name', 'checkboxValues');

                var span = $('<span>').addClass('checkmark');

                var label = $('<label>')
                    .attr('class','material-checkbox')
                    .attr('for', 'checkbox_' + columns[i])
                    .attr('id', 'checkbox_' + columns[i]);
                   

                label.append(checkbox).append(span).append(columns[i]);
                cell.append(label);
            }

            checkboxesLoaded = true;
        }
    }
});


function clearDropdown(dropdownId) {
    var dropdown = document.getElementById(dropdownId);
    dropdown.selectedIndex = 0;
    // Additional logic to clear dynamically added options if needed
}

/************ Taken out of metric data download pop up *************/
function toggleVisualization(id) {
    var element = document.getElementById(id);
    if (element.style.display === 'none' || element.style.display === '') {
        element.style.display = 'block';
    } else {
        element.style.display = 'none';
    }
}


