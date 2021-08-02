<?php
require 'connection.php';


function setStart($offSet){
    $theStart = new DateTime('now');
    date_add($theStart, date_interval_create_from_date_string($offSet. " days"));
    return $theStart;
}


// round to this many digits because otherwise it's overkill
$lat = floatval($_GET['lat']);
$long = floatval($_GET['long']);
$offset = intval($_GET['dateOffset']);
$startDate = setStart($offset);
$tz = intval($_GET['tz']);
$numDays = strval($_GET['numDays']);
if('' == $numDays)
{
  // get all data if not specified
  $numDays = 999;
}
$member = strval($_GET['member']);
$model = strtoupper(strval($_GET['model']));
$mode = strval($_GET['mode']);
$is_daily = true;
if ($mode == '' or $mode == 'hourly')
{
  $is_daily = false;
}
else if ($mode != 'daily')
{
  echo('Invalid mode specified - must be daily or hourly');
  exit();
}
function modelArray($last_row, $membersArray)
{
    if(is_null($last_row['generated']))
    {
        echo('No historic match data exists');
        exit();
    }
    return array(
            // these are all Zulu times
            "Generated" => $last_row['generated'],
            "lat"=>floatval($last_row['latitude']),
            "lon"=>floatval($last_row['longitude']),
            // this is in meters, so no decimal digits should be fine
            "DistanceFrom" => round($last_row['distance_from']),
            "Members" => $membersArray
        );
}

function roundValue($index, $value)
{  
  $numDigits = array(
      'tmp' => 1,
      'rh' => 0,
      'ws' => 1,
      'wd' => 0,
      'apcp' => 2
  );
 // NOTE: didn't work with this as a global variable (rounded to 0 digits)
  // $num_digits = 2;
  // return round($value, $num_digits);
  // echo $index;
  // echo $numDigits[$index];
  return round($value, $numDigits[$index]);
}

function readModels($conn, $sql, $indices, &$dates_array)
{
    $stmt = try_query($conn,$sql);
    $modelsArray = array();
    $last_model = null;
    $last_member = null;
    $last_generated = null;
    $last_row = null;
    $last_key = null;
    $is_same = null;
    while( $row = pg_fetch_array($stmt) ) {
        $cur_model = $row['model'];
        $cur_member = $row['member'];
        $temp = array();
        // output all the indices that we said we're going to provide
        foreach ($indices as $i=>$var) {
            array_push($temp, roundValue($var, $row[$var]));
        }
        $is_same = $last_member == $cur_member && $last_model == $cur_model;
        // either new member or model
        if ($last_member != $cur_member || $last_model != $cur_model) {
            if (!is_null($last_row)) {
                $membersArray[$last_member] = $dataArray;
            }
            $dataArray = array();
            $last_member = $cur_member;
            
            // push all members into model array if new model
            if ($last_model != $cur_model) {
                if (!is_null($last_model)) {
                    $modelsArray[$last_model] = modelArray($last_row, $membersArray);
                }
                
                $membersArray = array();
                $last_model = $cur_model;
            }
        }
        $cur_date = $row['fortime'].' GMT';
        // use a single array of dates and then the index in that array for the members
        if (!in_array($cur_date, $dates_array)) {
            array_push($dates_array, $cur_date);
        }
        $date_key = array_search($cur_date, $dates_array);
        // if ($is_same && $last_key != ($date_key - 1))
        // {
            //HACK: output is missing a day so just duplicate
            // $dataArray[$date_key - 1] = $temp;
        // }
        $last_key = $date_key;
        $dataArray[$date_key] = $temp;
        $last_row = $row;
    }
    if (!is_null($last_member)) {
        $membersArray[$last_member] = $dataArray;
    }
    if (!is_null($last_model)) {
        $modelsArray[$last_model] = modelArray($last_row, $membersArray);
    }
    return $modelsArray;
}
date_default_timezone_set('GMT');
$zone = null;
if ('' != $tz)
{
  $zone_str = 'GMT'.$tz;
  if ($tz >= 0)
  {
    $zone_str = 'GMT+'.$tz;
  }
  $zone = new DateTimeZone($zone_str);
}
$conn = connect('FireGUARD');
if ($conn){
    $indices = array(
        'tmp',
        'rh',
        'ws',
        'wd',
        'apcp'
    );
    $outputArray = array();
    $dates_array = array();
    
    $sql = "SELECT *"
        . " FROM INPUTS.FCT_Forecast_By_Offset(".$offset.", ".$lat.", ".$long.", ".$numDays.")"
        . " WHERE 1=1";
    if ('' != $member)
    {
      $sql = $sql . " AND member=" . $member;
    }
    if ('' != $model)
    {
      $sql = $sql . " AND model='" . $model . "'";
    }
    $sql = $sql
        . "  order by model, member, fortime";
    $outputArray['Models'] = readModels($conn, $sql, $indices, $dates_array);
    $outputArray['ForDates'] = $dates_array;
    // we only need to know the day we started since they're sequential
    $outputArray['StartDate'] = $dates_array[0];
    // echo json_encode($outputArray);
    header('Content-type: application/csv');
    header('Content-Disposition: attachment; filename=wx.csv');
    $EOL = "\n";
    // $EOL = "<br />";
    $first_day = intval(date_format(new DateTime($dates_array[0]), 'Ymd'));
    if ($is_daily)
    {
      echo "DAILY";
    }
    else
    {
      echo "HOURLY,HOUR";
    }
    if ('' == $model)
    {
      echo ",MODEL";
    }
    if ('' == $member)
    {
      echo ",MEMBER";
    }
    echo ",TEMP,RH,WD,WS,PREC".$EOL;
    $fixed_dates = array();
    $diff_noon =  array();
    $best_diff = array();
    foreach ($dates_array as $j=>$d)
    {
      $for_time = $dates_array[$j];
      $time = new DateTime($for_time);
      if (!is_null($zone))
      {
        $time->setTimezone($zone);
      }
      $fixed_dates[$j] = $time;
      $diff_noon[$j] = 12 - intval(date_format($time, 'G'));
      $date = intval(date_format($time, 'Ymd'));
      # >= to prefer later in the day over earlier
      if (is_null($best_diff[$date]) || (abs($best_diff[$date]) >= abs($diff_noon[$j])))
      {
        if ($diff_noon[$j] <= 3)
        {
          // NOTE: since max interval is 6 hours, we should always be within 3 of some timestep
          // absolute max distance to time from noon, otherwise don't include day
          $best_diff[$date] = $diff_noon[$j];
        }
      }
    }
    foreach ($outputArray['Models'] as $x=>$cur_model)
    {
      foreach($cur_model['Members'] as $i=>$m) {
        $old_rain = 0;
        // foreach ($fixed_dates as $j=>$for_time) {
          // $v = $m[$j];
        foreach ($m as $j=>$v) {
          $for_time = $fixed_dates[$j];
          $date = intval(date_format($for_time, 'Ymd'));
          // check if tz offset puts this before start day
          $before_start = $date < $first_day;
          if (!$is_daily || (!$before_start && $best_diff[$date] == $diff_noon[$j]))
          {
            echo date_format($for_time, "Y-m-d");
            if(!$is_daily)
            {
              echo date_format($for_time, ",G");
            }
            // echo ",".$diff_noon[$j];
            if ('' == $model)
            {
              echo ",".$x;
            }
            if ('' == $member)
            {
              echo ",".$i;
            }
            # do these manually so we can treat rain differently and not have a loop plus that
            echo ",".roundValue('tmp', $v[0]);
            echo ",".roundValue('rh', $v[1]);
            echo ",".roundValue('ws', $v[2]);
            echo ",".roundValue('wd', $v[3]);
            $cur_rain = $v[4] - $old_rain;
            $old_rain = $v[4];
            echo ",".roundValue('apcp', $cur_rain);
            echo $EOL;
          }
        }
      }
    }
    // echo json_encode($outputArray);
}
else{
    echo("Error could not connect to SQL database: ".print_r( pg_errors(), true));
}

/* Close the connection. */
pg_close( $conn);
?>
