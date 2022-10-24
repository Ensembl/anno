# See the NOTICE file distributed with this work for additional information
# regarding copyright ownership.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# standard library
import errno
import logging
import os
import pathlib
import re
import shutil
import sys

from typing import Union


# logging formats
logging_formatter_time_message = logging.Formatter(
    fmt="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# set up base logger
logger = logging.getLogger("main_logger")
logger.setLevel(logging.DEBUG)
logger.propagate = False
# create console handler and add to logger
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging_formatter_time_message)
logger.addHandler(console_handler)


def add_log_file_handler(
    logger: logging.Logger,
    log_file_path: Union[pathlib.Path, str],
    logging_formatter: logging.Formatter = logging_formatter_time_message,
):
    """
    Create file handler and add to logger.
    """
    file_handler = logging.FileHandler(log_file_path, mode="a+")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging_formatter)
    logger.addHandler(file_handler)


def check_exe(exe_path):
    if not shutil.which(exe_path):
        raise OSError('Executable file not found at "%s"' % exe_path)


def check_file(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), file_path)


def check_gtf_content(gtf_file: Union[pathlib.Path, str], content_obj):
    """
    This just checks how many transcript lines are in a GTF
    """
    transcript_count = 0
    with open(gtf_file) as gtf_in:
        for line in gtf_in:
            eles = line.split("\t")
            if not len(eles) == 9:
                continue
            if eles[2] == content_obj:
                transcript_count += 1
    logger.info("%s GTF transcript count: %s" % (gtf_file, transcript_count))
    return transcript_count


def create_dir(main_output_dir: Union[pathlib.Path, str], dir_name: str = None):
    """
    Create directory or subdirectory and log operations.
    Args:
        main_output_dir: main output directory path
        dir_name: optional subdirectory to be created
    Returns:
        created directory Path object
    """
    main_output_dir = pathlib.Path(main_output_dir)

    if dir_name:
        target_dir = main_output_dir / dir_name
    else:
        target_dir = main_output_dir

    try:
        target_dir.mkdir()
    except FileExistsError:
        logger.warning('Directory "%s" already exists' % target_dir)
    except OSError:
        logger.error('Failed to create directory "%s"' % target_dir)
        sys.exit()
    else:
        logger.info('Successfully created directory "%s"' % target_dir)

    return target_dir


def create_paired_paths(fastq_file_paths):
    """
    TODO
    standardize to str or pathlib.Path paths
    """
    path_dict = {}
    final_list = []

    for path in fastq_file_paths:
        match = re.search(r"(.+)_\d+\.(fastq|fq)", str(path))
        if not match:
            logger.error(
                "Could not find _1 or _2 at the end of the prefix for file. Assuming file is not paired: %s"
                % path
            )
            final_list.append([path])
            continue

        prefix = match.group(1)
        if prefix in path_dict:
            # path_dict[prefix] = path_dict[prefix] + ',' + path
            path_dict[prefix].append(path)
        else:
            path_dict[prefix] = [path]

    for pair in path_dict:
        final_list.append(path_dict[pair])

    return final_list


def get_seq_region_lengths(genome_file: Union[pathlib.Path, str], min_seq_length: int):
    current_header = ""
    current_seq = ""

    seq_regions = {}
    with open(genome_file) as file_in:
        for line in file_in:
            match = re.search(r">(.+)$", line)
            if match and current_header:
                if len(current_seq) > min_seq_length:
                    seq_regions[current_header] = len(current_seq)

                current_seq = ""
                current_header = match.group(1)
            elif match:
                current_header = match.group(1)
            else:
                current_seq += line.rstrip()

        if len(current_seq) > min_seq_length:
            seq_regions[current_header] = len(current_seq)

    return seq_regions


def prlimit_command(command_list: list, virtual_memory_limit: int):
    """
    Uses the `prlimit` program to set a memory limit for a command list to be run with subprocess.
    prlimit - get and set process resource limits
    -v, --as[=limits]
        Address space limit.
    Args:
        command_list: original subprocess command list
        virtual_memory_limit: virtual memory limit in bytes
    Returns:
        memory limited subprocess command list
    """
    return ["prlimit", f"-v{virtual_memory_limit}"] + command_list

def load_results_to_ensembl_db(
    main_script_dir: pathlib.Path,
    load_to_ensembl_db,
    genome_file: Union[pathlib.Path, str],
    main_output_dir: pathlib.Path,
    db_details,
    num_threads: int,
):
    db_loading_script = main_script_dir / "support_scripts_perl" / "load_gtf_ensembl.pl"
    db_loading_dir = create_dir(main_output_dir, "db_loading")

    # Should collapse this into a function
    annotation_results_gtf_file = (
        main_output_dir / "annotation_output" / "annotation.gtf"
    )
    if annotation_results_gtf_file.exists():
        logger.info("Loading main geneset to db")
        batch_size = 200
        load_type = "gene"
        analysis_name = "ensembl"
        gtf_records = batch_gtf_records(
            annotation_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "Main gene annotation file not found, can't load:\n%s"
            % annotation_results_gtf_file
        )

    rfam_results_gtf_file = main_output_dir / "rfam_output" / "annotation.gtf"
    if rfam_results_gtf_file.exists():
        logger.info("Loading Rfam-based sncRNA genes to db")
        batch_size = 500
        load_type = "gene"
        analysis_name = "ncrna"
        gtf_records = batch_gtf_records(
            rfam_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "Rfam annotation file not found, can't load:\n%s" % rfam_results_gtf_file
        )

    trnascan_results_gtf_file = main_output_dir / "trnascan_output" / "annotation.gtf"
    if trnascan_results_gtf_file.exists():
        logger.info("Loading tRNAScan-SE tRNA genes to db")
        batch_size = 500
        load_type = "gene"
        analysis_name = "ncrna"
        gtf_records = batch_gtf_records(
            trnascan_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "tRNAScan-SE annotation file not found, can't load:\n%s"
            % trnascan_results_gtf_file
        )

    dust_results_gtf_file = main_output_dir / "dust_output" / "annotation.gtf"
    if dust_results_gtf_file.exists():
        logger.info("Loading Dust repeats to db")
        batch_size = 500
        load_type = "single_line_feature"
        analysis_name = "dust"
        gtf_records = batch_gtf_records(
            dust_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "Dust annotation file not found, can't load:\n%s" % dust_results_gtf_file
        )

    red_results_gtf_file = main_output_dir / "red_output" / "annotation.gtf"
    if red_results_gtf_file.exists():
        logger.info("Loading Red repeats to db")
        batch_size = 500
        load_type = "single_line_feature"
        analysis_name = "repeatdetector"
        gtf_records = batch_gtf_records(
            red_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "Red annotation file not found, can't load:\n%s" % red_results_gtf_file
        )

    trf_results_gtf_file = main_output_dir / "trf_output" / "annotation.gtf"
    if trf_results_gtf_file.exists():
        logger.info("Loading TRF repeats to db")
        batch_size = 500
        load_type = "single_line_feature"
        analysis_name = "trf"
        gtf_records = batch_gtf_records(
            trf_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "TRF annotation file not found, can't load:\n%s" % trf_results_gtf_file
        )

    cpg_results_gtf_file = main_output_dir / "cpg_output" / "annotation.gtf"
    if cpg_results_gtf_file.exists():
        logger.info("Loading CpG islands to db")
        batch_size = 500
        load_type = "single_line_feature"
        analysis_name = "cpg"
        gtf_records = batch_gtf_records(
            cpg_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "CpG annotation file not found, not loading:\n%s" % cpg_results_gtf_file
        )

    eponine_results_gtf_file = main_output_dir / "eponine_output" / "annotation.gtf"
    if eponine_results_gtf_file.exists():
        logger.info("Loading Eponine repeats to db")
        batch_size = 500
        load_type = "single_line_feature"
        analysis_name = "eponine"
        gtf_records = batch_gtf_records(
            eponine_results_gtf_file, batch_size, db_loading_dir, load_type
        )
        generic_load_records_to_ensembl_db(
            load_to_ensembl_db,
            db_loading_script,
            genome_file,
            db_details,
            db_loading_dir,
            load_type,
            analysis_name,
            gtf_records,
            num_threads,
        )
    else:
        logger.error(
            "Eponine annotation file not found, can't load:\n%s"
            % eponine_results_gtf_file
        )

    logger.info("Finished loading records to db")


def generic_load_records_to_ensembl_db(
    load_to_ensembl_db,
    db_loading_script,
    genome_file: Union[pathlib.Path, str],
    db_details,
    db_loading_dir,
    load_type,
    analysis_name,
    gtf_records,
    num_threads: int,
):
    pool = multiprocessing.Pool(num_threads)
    for record_batch in gtf_records:
        pool.apply_async(
            multiprocess_load_records_to_ensembl_db,
            args=(
                load_to_ensembl_db,
                db_loading_script,
                genome_file,
                db_details,
                db_loading_dir,
                load_type,
                analysis_name,
                record_batch,
            ),
        )

    pool.close()
    pool.join()


def multiprocess_load_records_to_ensembl_db(
    load_to_ensembl_db,
    db_loading_script,
    genome_file: Union[pathlib.Path, str],
    db_details,
    output_dir,
    load_type,
    analysis_name,
    record_batch,
):
    with tempfile.NamedTemporaryFile(
        mode="w+t", delete=False, dir=output_dir
    ) as gtf_temp_out:
        for line in record_batch:
            gtf_temp_out.write(line)
            gtf_temp_file_path = gtf_temp_out.name

    db_name, db_host, db_port, db_user, db_pass = db_details.split(",")

    loading_cmd = [
        "perl",
        db_loading_script,
        "-genome_file",
        genome_file,
        "-dbname",
        db_name,
        "-host",
        db_host,
        "-port",
        str(db_port),
        "-user",
        db_user,
        "-pass",
        db_pass,
        "-gtf_file",
        gtf_temp_file_path,
        "-analysis_name",
        analysis_name,
        "-load_type",
        load_type,
    ]

    if load_type == "gene" and analysis_name == "ensembl":
        loading_cmd.extend(
            [
                "-protein_coding_biotype",
                "anno_protein_coding",
                "-non_coding_biotype",
                "anno_lncRNA",
            ]
        )

        if load_to_ensembl_db == "single_transcript_genes":
            loading_cmd.append("-make_single_transcript_genes")

    logger.info("loading_cmd: %s" % " ".join(loading_cmd))
    subprocess.run(loading_cmd)
    gtf_temp_out.close()
    os.remove(gtf_temp_file_path)  # NOTE: doesn't seem to be working
    logger.info("Finished: %s" % gtf_temp_file_path)
    gc.collect()


def batch_gtf_records(input_gtf_file, batch_size, output_dir, record_type):
    records = []
    with open(input_gtf_file) as gtf_in:
        if record_type == "gene":
            # NOTE that the neverending variations on GTF reading/writing/merging is becoming very messy
            # need to create a set of utility methods outside of this script
            # This one assumes the file has unique ids for the parent features. It then batches them into
            # sets of records based on the batch size passed in
            record_counter = 0
            current_record_batch = []
            current_gene_id = ""
            for line in gtf_in:
                if re.search(r"^#", line):
                    continue

                eles = line.split("\t")
                if not len(eles) == 9:
                    continue

                match = re.search(r'gene_id "([^"]+)"', line)
                gene_id = match.group(1)

                if not current_gene_id:
                    record_counter += 1
                    current_gene_id = gene_id

                if not gene_id == current_gene_id:
                    record_counter += 1
                    if record_counter % batch_size == 0:
                        records.append(current_record_batch)
                        current_record_batch = []
                    current_gene_id = gene_id

                current_record_batch.append(line)

            records.append(current_record_batch)

        elif record_type == "single_line_feature":
            record_counter = 0
            current_record_batch = []
            current_gene_id = ""
            for line in gtf_in:
                if re.search(r"^#", line):
                    continue

                eles = line.split("\t")
                if not len(eles) == 9:
                    continue

                record_counter += 1

                if record_counter % batch_size == 0:
                    records.append(current_record_batch)
                    current_record_batch = []

                current_record_batch.append(line)

            records.append(current_record_batch)

    return records    
