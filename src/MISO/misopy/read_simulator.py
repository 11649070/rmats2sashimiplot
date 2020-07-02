from scipy import *
from numpy.random import multinomial, binomial, negative_binomial, normal, randint
import misopy
from misopy.parse_csv import find

def print_reads_summary(reads, gene, paired_end=False):
    num_isoforms = len(gene.isoforms)
    computed_const = False
    num_constitutive_reads = 0

    for n in range(num_isoforms):
        unambig_read = zeros(num_isoforms, dtype=int)
        unambig_read[n] = 1
        num_iso_reads = 0
        for r in reads:
            if paired_end:
                curr_read = r[0]
            else:
                curr_read = r
            if all(curr_read == unambig_read):
                num_iso_reads += 1
            if not computed_const:
                # If didn't compute so already, calculate how many reads
                # are constitutive, i.e. consistent with all isoforms
                if all(array(curr_read) == 1):
                    num_constitutive_reads += 1
        computed_const = True
        print "Iso %d (len = %d): %d unambiguous supporting reads" %(n, gene.isoforms[n].len,
                                                                     num_iso_reads)
    print "No. constitutive reads (consistent with all): %d" %(num_constitutive_reads)

def get_reads_summary(reads):
    if reads.ndim != 2:
        raise Exception, "get_reads_summary only defined for two-isoform."
    ni = 0
    ne = 0
    nb = 0
    for read in reads:
        if read[0] == 1 and read[1] == 0:
            # NI read
            ni += 1
        elif read[0] == 0 and read[1] == 1:
            # NE read
            ne += 1
        elif read[0] == 1 and read[1] == 1:
            nb += 1
    return (ni, ne, nb)

def expected_read_summary(gene, true_psi, num_reads, read_len, overhang_len):
    """
    Computed the expected number of NI, NE, NB and number of reads excluded
    due to overhang constraints.  Note that:

    NI + NE + NB = number of reads not excluded by overhang
                 = 1 - reads excluded by overhang
    """
    # Compute probability of overhang violation:
    # p(oh violation) = p(oh violation | isoform1)p(isoform1) + p(oh violation | isoform2)p(isoform2)
    ##
    ## Assumes first isoform has 3 exons, second has 2 exons
    ##
    parts = gene.parts
    iso1_seq = gene.isoforms[0].seq
    iso2_seq = gene.isoforms[1].seq
    num_pos_iso1 = len(iso1_seq) - read_len + 1
    num_pos_iso2 = len(iso2_seq) - read_len + 1
    psi_f = (true_psi*num_pos_iso1)/((true_psi*num_pos_iso1) + ((1-true_psi)*num_pos_iso2))
    ##
    ## Try a version that takes into account overhang!
    ##
    p_oh_violation = (((2*(overhang_len-1)*2)/float(num_pos_iso1))*psi_f) + \
                     ((2*(overhang_len-1)/float(num_pos_iso2))*(1-psi_f))
    # Compute probability of inclusion read:
    # p(NI) = p(isoform 1)p(inclusion read | isoform 1)
    skipped_exon_len = gene.get_part_by_label('B').len
    p_NI = psi_f*(((skipped_exon_len - read_len + 1) + 2*(read_len + 1 - 2*overhang_len)) / \
                  float(len(iso1_seq) - read_len + 1))
    # Compute probability of exclusion read:
    # p(NE) = p(isoform 2)p(exclusion read | isoform 2)
    p_NE = (1-psi_f)*((read_len + 1 - (2*overhang_len))/float(len(iso2_seq) - read_len + 1))
    # Compute probability of read supporting both:
    # p(NB) = p(isoform 1)p(NB read | isoform 1) + p(isoform 2)p(NB read | isoform 2)
    num_NB = (gene.get_part_by_label('A').len - read_len + 1) + (gene.get_part_by_label('C').len - read_len + 1)
    p_NB = psi_f*((num_NB)/float(len(iso1_seq) - read_len + 1)) + \
           (1-psi_f)*(num_NB/float(len(iso2_seq) - read_len + 1))
    print "p_NI: %.5f, p_NE: %.5f, p_NB: %.5f" %(p_NI, p_NE, p_NB)
    return [p_NI*num_reads, p_NE*num_reads, p_NB*num_reads, p_oh_violation*num_reads]

def simulate_two_iso_reads(gene, true_psi, num_reads, read_len, overhang_len,
                           p_ne_loss=0, p_ne_gain=0, p_ni_loss=0, p_ni_gain=0):
    """
    Return a list with an element for each isoform, saying whether the read could have
    been generated by that isoform (denoted 1) or not (denoted 0).
    """
    if len(gene.isoforms) != 2:
        raise Exception, "simulate_two_iso_reads requires a gene with only two isoforms."
    if len(true_psi) < 2:
        raise Exception, "Simulate reads requires a probability vector of size > 2."
    reads_summary = [0, 0, 0]
    all_reads = []
    categories = []
    true_isoforms = []
    noise_probs = array([p_ne_loss, p_ne_gain, p_ni_loss, p_ni_gain])
    noisify = any(noise_probs > 0)
    noiseless_counts = [0, 0, 0]
    for k in range(0, num_reads):
        reads_sampled = sample_random_read(gene, true_psi, read_len, overhang_len)
        read_start, read_end = reads_sampled[1]
        category = reads_sampled[2]
        chosen_iso = reads_sampled[3]
        reads_sampled = reads_sampled[0]
        single_read = (reads_sampled[0] + reads_sampled[2], reads_sampled[1] + reads_sampled[2])
        NI, NE, NB = reads_sampled
        # If read was not thrown out due to overhang, include it
        if any(array(single_read) != 0):
            noiseless_counts[0] += NI
            noiseless_counts[1] += NE
            noiseless_counts[2] += NB
            # Check if read was chosen to be noised
            if noisify:
                # If exclusive isoform was sampled and we decided to noise it, discard the read
                if (p_ne_loss > 0) and (chosen_iso == 1) and (rand() < p_ne_loss):
                    # Note that in this special case of a gene with two isoforms,
                    # 'reads_sampled' is a read summary tuple of the form (NI, NE, NB)
                    # and not an alignment to the two isoforms.
                    if reads_sampled[1] == 1:
                        # If read came from exclusion junction (NE), discard it
                        continue
                if (p_ne_gain > 0) and (chosen_iso == 1) and (rand() < p_ne_gain):
                    if reads_sampled[1] == 1:
                        # Append read twice
                        all_reads.extend([single_read, single_read])
                        # Find what category read landed in and increment it
                        cat = reads_sampled.index(1)
                        reads_sampled[cat] += 1
            all_reads.append(single_read)
            categories.append(category)
            prev_reads_summary = reads_summary
            reads_summary[0] += reads_sampled[0]
            reads_summary[1] += reads_sampled[1]
            reads_summary[2] += reads_sampled[2]
            true_isoforms.append(chosen_iso)
#    if p_ne_gain > 0:
#        print "--> No noise NI: %d, NE: %d, NB: %d" %(noiseless_counts[0], noiseless_counts[1],
#                                                      noiseless_counts[2])
#        print "    noised: ", reads_summary
    all_reads = array(all_reads)
    return (reads_summary, all_reads, categories, true_isoforms)

def simulate_reads(gene, true_psi, num_reads, read_len, overhang_len):
    """
    Return a list of reads.  Each read is a vector of the size of the number of isoforms, with 1
    if the read could have come from the isoform and 2 otherwise.
    """
    if type(true_psi) != list:
        raise Exception, "simulate_reads: expects true_psi to be a probability vector summing to 1."
    if len(gene.isoforms) == 2:
        raise Exception, "simulate_reads: should use simulate_two_iso_reads for genes with only two isoforms."
    if sum(true_psi) != 1:
        raise Exception, "simulate_reads: true_psi must sum to 1."
    all_reads = []
    read_coords = []
    if len(true_psi) < 2:
        raise Exception, "Simulate reads requires a probability vector of size > 2."
    for k in range(0, num_reads):
        reads_sampled = sample_random_read(gene, true_psi, read_len, overhang_len)
        alignment = reads_sampled[0]
        read_start, read_end = reads_sampled[1]
        category = reads_sampled[2]
        reads_sampled = reads_sampled[0]
        if any(alignment != 0):
            # If read was not thrown out due to overhang, include it
            all_reads.append(alignment)
            read_coords.append((read_start, read_end))
    all_reads = array(all_reads)
    return (all_reads, read_coords)

def check_paired_end_read_consistency(reads):
    """
    Check that a set of reads are consistent with their fragment lengths,
    i.e. that reads that do not align to an isoform have a -Inf fragment length,
    and reads that are alignable to an isoform do not have a -Inf fragment length.
    """
    pe_reads = reads[:, 0]
    frag_lens = reads[:, 1]
    num_reads = len(pe_reads)
    print "Checking read consistency for %d reads..." %(num_reads)
    print reads
    is_consistent = False
    is_consistent = all(frag_lens[nonzero(pe_reads == 1)] != -Inf)
    if not is_consistent:
        return is_consistent
    is_consistent = all(frag_lens[nonzero(pe_reads == 0)] == -Inf)
    return is_consistent

##
## Diffrent fragment length distributions.
##
def sample_binomial_frag_len(frag_mean=200, frag_variance=100):
    """
    Sample a fragment length from a binomial distribution parameterized with a
    mean and variance.

    If frag_variance > frag_mean, use a Negative-Binomial distribution.
    """
    assert(abs(frag_mean - frag_variance) > 1)
    if frag_variance < frag_mean:
        p = 1 - (frag_variance/float(frag_mean))
        # N = mu/(1-(sigma^2/mu))
        n = float(frag_mean) / (1 - (float(frag_variance)/float(frag_mean)))
        return binomial(n, p)
    else:
        r = -1 * (power(frag_mean, 2)/float(frag_mean - frag_variance))
        p = frag_mean / float(frag_variance)
        print "Sampling frag_mean=",frag_mean, " frag_variance=", frag_variance
        print "r: ",r, "  p: ", p
        return negative_binomial(r, p)

def compute_rpkc(list_read_counts, const_region_lens, read_len):
    """
    Compute the RPKC (reads per kilobase of constitutive region) for the set of constitutive regions.
    These are assumed to be constitutive exon body regions (not including constitutive junctions.)
    """
    num_mappable_pos = 0
#    assert(len(list_read_counts) == len(const_region_lens))
    for region_len in const_region_lens:
        num_mappable_pos += region_len - read_len + 1
    read_counts = sum(list_read_counts)
    rpkc = read_counts / (num_mappable_pos / 1000.)
    return rpkc

def sample_normal_frag_len(frag_mean, frag_variance):
    """
    Sample a fragment length from a rounded 'discretized' normal distribution.
    """
    frag_len = round(normal(frag_mean, sqrt(frag_variance)))
    return frag_len

def simulate_paired_end_reads(gene, true_psi, num_reads, read_len, overhang_len, mean_frag_len,
                              frag_variance, bino_sampling=False):
    """
    Return a list of reads that are aligned to isoforms.
    This list is a pair, where the first element is a list of read alignments
    and the second is a set of corresponding fragment lengths for each alignment.
    """
    if sum(true_psi) != 1:
        raise Exception, "simulate_reads: true_psi must sum to 1."
    # sample reads
    reads = []
    read_coords = []
    assert(frag_variance != None)
    sampled_frag_lens = []
    for k in range(0, num_reads):
        # choose a fragment length
        insert_len = -1
        while insert_len < 0:
            if bino_sampling:
                frag_len = sample_binomial_frag_len(frag_mean=mean_frag_len, frag_variance=frag_variance)
            else:
                frag_len = sample_normal_frag_len(frag_mean=mean_frag_len, frag_variance=frag_variance)
            insert_len = frag_len - (2 * read_len)
            if insert_len < 0:
                raise Exception, "Sampled fragment length that is shorter than 2 * read_len!"
                #print "Sampled fragment length that is shorter than 2 * read_len!"
            sampled_frag_lens.append(frag_len)
        reads_sampled = sample_random_read_pair(gene, true_psi, read_len, overhang_len, insert_len, mean_frag_len)
        alignment = reads_sampled[0]
        frag_lens = reads_sampled[1]
        read_coords.append(reads_sampled[2])
        reads.append([alignment, frag_lens])
    return (array(reads), read_coords, sampled_frag_lens)

# def compute_read_pair_position_prob(iso_len, read_len, insert_len):
#     """
#     Compute the probability that the paired end read of the given read length and
#     insert size will start at each position of the isoform (uniform.)
#     """
#     read_start_prob = zeros(iso_len)
#     # place a 1 in each position if a read could start there (0-based index)
#     for start_position in range(iso_len):
#       # total read length, including insert length and both mates
#       paired_read_len = 2*read_len + insert_len
#       if start_position + paired_read_len <= iso_len:
#           read_start_prob[start_position] = 1
#     # renormalize ones to get a probability vector
#     possible_positions = nonzero(read_start_prob)[0]
#     if len(possible_positions) == 0:
#       return read_start_prob
#     num_possible_positions = len(possible_positions)
#     read_start_prob[possible_positions] = 1/float(num_possible_positions)
#     return read_start_prob

def compute_read_pair_position_prob(iso_len, read_len, frag_len):
    """
    Compute the probability that the paired end read of the given fragment length
    will start at each position of the isoform (uniform.)
    """
    read_start_prob = zeros(iso_len)
    # place a 1 in each position if a read could start there (0-based index)
    for start_position in range(iso_len):
        # total read length, including insert length and both mates
        if start_position + frag_len - 1 <= iso_len - 1:
            read_start_prob[start_position] = 1
    # renormalize ones to get a probability vector
    possible_positions = nonzero(read_start_prob)[0]
    if len(possible_positions) == 0:
        return read_start_prob
    num_possible_positions = len(possible_positions)
    read_start_prob[possible_positions] = 1/float(num_possible_positions)
    return read_start_prob

def sample_random_read_pair(gene, true_psi, read_len, overhang_len, insert_len, mean_frag_len):
    """
    Sample a random paired-end read (not taking into account overhang) from the
    given a gene, the true Psi value, read length, overhang length and the insert length (fixed).

    A paired-end read is defined as (genomic_left_read_start, genomic_left_read_end,
                                     genomic_right_read_start, genomic_right_read_start).

    Note that if we're given a gene that has only two isoforms, the 'align' function of
    gene will return a read summary in the form of (NI, NE, NB) rather than an alignment to
    the two isoforms (which is a pair (0/1, 0/1)).
    """
    iso_lens = [iso.len for iso in gene.isoforms]
    num_positions = array([(l - mean_frag_len + 1) for l in iso_lens])
    # probability of sampling a particular position from an isoform -- assume uniform for now
    iso_probs = [1/float(n) for n in num_positions]
    psi_frag_denom = sum(num_positions * array(true_psi))
    psi_frags = [(num_pos * curr_psi)/psi_frag_denom for num_pos, curr_psi \
                 in zip(num_positions, true_psi)]
    # Choose isoform to sample read from
    chosen_iso = list(multinomial(1, psi_frags)).index(1)
    iso_len = gene.isoforms[chosen_iso].len
    frag_len = insert_len + 2*read_len
    isoform_position_probs = compute_read_pair_position_prob(iso_len, read_len, frag_len)
    # sanity check
    left_read_start = list(multinomial(1, isoform_position_probs)).index(1)
    left_read_end = left_read_start + read_len - 1
    # right read starts after the left read and the insert length
    right_read_start = left_read_start + read_len + insert_len
    right_read_end = left_read_start + (2*read_len) + insert_len - 1
    # convert read coordinates from coordinates of isoform that generated it to genomic coordinates
    genomic_left_read_start, genomic_left_read_end = \
                             gene.isoforms[chosen_iso].isoform_coords_to_genomic(left_read_start,
                                                                                 left_read_end)

    genomic_right_read_start, genomic_right_read_end = \
                              gene.isoforms[chosen_iso].isoform_coords_to_genomic(right_read_start,
                                                                                  right_read_end)
    # parameterized paired end reads as the start coordinate of the left
    pe_read = (genomic_left_read_start, genomic_left_read_end,
               genomic_right_read_start, genomic_right_read_end)
    alignment, frag_lens = gene.align_read_pair(pe_read[0], pe_read[1], pe_read[2], pe_read[3],
                                               overhang=overhang_len)
    return (alignment, frag_lens, pe_read)

def sample_random_read(gene, true_psi, read_len, overhang_len):
    """
    Sample a random read (not taking into account overhang) from the
    given set of exons and the true Psi value.

    Note that if we're given a gene that has only two isoforms, the 'align' function of
    gene will return a read summary in the form of (NI, NE, NB) rather than an alignment to
    the two isoforms (which is a pair (0/1, 0/1)).
    """
    iso_lens = [iso.len for iso in gene.isoforms]
    num_positions = array([(l - read_len + 1) for l in iso_lens])
    # probability of sampling a particular position from an isoform -- assume uniform for now
    iso_probs = [1/float(n) for n in num_positions]
    psi_frag_denom = sum(num_positions * array(true_psi))
    psi_frags = [(num_pos * curr_psi)/psi_frag_denom for num_pos, curr_psi \
                 in zip(num_positions, true_psi)]
    # Choose isoform to sample read from
    chosen_iso = list(multinomial(1, psi_frags)).index(1)
    isoform_position_prob = ones(num_positions[chosen_iso]) * iso_probs[chosen_iso]
    sampled_read_start = list(multinomial(1, isoform_position_prob)).index(1)
    sampled_read_end = sampled_read_start + read_len - 1
#    seq = gene.isoforms[chosen_iso].seq[sampled_read_start:sampled_read_end]
#    alignment, category = gene.align(seq, overhang=overhang_len)
    ##
    ## Trying out new alignment method
    ##
    # convert coordinates to genomic
    genomic_read_start, genomic_read_end = \
                        gene.isoforms[chosen_iso].isoform_coords_to_genomic(sampled_read_start,
                                                                            sampled_read_end)
    alignment, category = gene.align_read(genomic_read_start, genomic_read_end, overhang=overhang_len)
    return (tuple(alignment), [sampled_read_start, sampled_read_end], category, chosen_iso)

def read_counts_to_read_list(ni, ne, nb):
    """
    Convert a set of read counts for a two-isoform gene (NI, NE, NB) to a list of reads.
    """
    reads = []
    reads.extend(ni * [[1, 0]])
    reads.extend(ne * [[0, 1]])
    reads.extend(nb * [[1, 1]])
    return array(reads)

# def sample_random_read(gene, true_psi, read_len, overhang_len):
#     """
#     Sample a random read (not taking into account overhang) from the
#     given set of exons and the given true Psi value.
#     """
#     iso1_len = gene.isoforms[0]['len']
#     iso2_len = gene.isoforms[1]['len']
#     num_inc = 0
#     num_exc = 0
#     num_both = 0
#     num_positions_iso1 = iso1_len - read_len + 1
#     num_positions_iso2 = iso2_len - read_len + 1
#     p1 = 1/float(num_positions_iso1)
#     p2 = 1/float(num_positions_iso2)
#     psi_frag = (num_positions_iso1*true_psi)/((num_positions_iso1*true_psi + num_positions_iso2*(1-true_psi)))
#     # Choose isoform to sample read from
#     if rand() < psi_frag:
#         isoform_position_prob = ones(num_positions_iso1)*p1
#         sampled_read_start = list(multinomial(1, isoform_position_prob)).index(1)
#         sampled_read_end = sampled_read_start + read_len
#         seq = gene.isoforms[0]['seq'][sampled_read_start:sampled_read_end]
#         [n1, n2, nb], category = gene.align_two_isoforms(seq, overhang=overhang_len)
#         return [[n1, n2, nb], [sampled_read_start, sampled_read_end], category]
#     else:
#         isoform_position_prob = ones(num_positions_iso2)*p2
#         sampled_read_start = list(multinomial(1, isoform_position_prob)).index(1)
#         sampled_read_end = sampled_read_start + read_len
#         seq = gene.isoforms[1]['seq'][sampled_read_start:sampled_read_end]
#         [n1, n2, nb], category = gene.align_two_isoforms(seq, overhang=overhang_len)
#         return [[n1, n2, nb], [sampled_read_start, sampled_read_end], category]
